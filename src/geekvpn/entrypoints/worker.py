"""The background worker.

Every scheduled behaviour this platform promises lived in code that nothing ever
called: ``NotificationScheduler``, ``ReminderService``, the payment verification
sweeper, and - once the provisioning layer existed - the retry queue for orders
whose panel was down at the moment of purchase. ``docker-compose.prod.yml`` ran
an API and a bot and nothing else.

This is the missing process.

Design notes
------------

**One process, a simple loop, no Celery.** The workload is a handful of jobs on
minute-to-hour intervals against one database. A broker would add an operational
component, a serialisation format and a failure mode, and buy nothing at this
size. The seam is the scheduler, so moving to a broker later replaces this file
and nothing else.

**A single tick never runs two copies.** A Redis lock with a TTL guards the
whole tick. Two workers - or one worker and an operator running the job by
hand - would double-send reminders, and a customer who gets the same "your
service expires in 3 days" message twice trusts the next one less.

**A failing job does not stop the loop.** ``TickReport`` already separates ran
from failed; the loop logs failures and continues. One unreachable panel must
not stop expiry reminders going out.

**Provisioning is drained more often than anything else.** A customer waiting
for the account they just paid for is the most time-sensitive thing here, so it
runs on its own short interval rather than through the notification schedule.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from types import FrameType
from typing import Any

from sqlalchemy import select

from geekvpn.application.notifications.operator_alerts import AlertKind
from geekvpn.application.notifications.scheduler import NotificationScheduler, TickReport
from geekvpn.application.platform.settings_service import DELETE_EXPIRED_AFTER_HOURS
from geekvpn.application.provisioning.expired_cleanup import ExpiredCleanup
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.infrastructure.backup.service import LAST_RUN_KEY as LAST_BACKUP_KEY
from geekvpn.infrastructure.backup.service import backup_settings, is_due, send_backup
from geekvpn.infrastructure.bot.auto_renew import build_auto_renewal
from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.di.container import Container, build_container, close_container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.di.sync_scope import build_sync_scope
from geekvpn.infrastructure.logging.setup import configure_logging, get_logger
from geekvpn.infrastructure.persistence.models.resellers import ResellerModel

#: How many scheduled broadcasts one tick will start.
#:
#: Small, because each one then sends to its whole audience before the next
#: begins - a tick that picks up fifty is a tick that runs for an hour.
_BROADCAST_BATCH = 5

logger = get_logger(__name__)

#: To the operators' service channel, so a deleted account is not a surprise
#: when its owner writes in a week later.
EXPIRED_REPORT_FA = "⌛ <b>{count} سرویس منقضی شد</b>"
CLEANUP_REPORT_FA = "🗑 <b>{count} سرویس منقضی حذف شد</b>\n\n<code>{names}</code>"

#: How often the loop wakes. The scheduler decides what is actually due, so this
#: is a resolution, not a job interval.
TICK_SECONDS = 30

#: Touched after every tick; the container healthcheck reads its age.
HEARTBEAT_PATH = Path("/tmp/worker-heartbeat")  # noqa: S108 - a container-local path

#: The provisioning retry queue runs on its own cadence. An order stuck because
#: a panel blipped should recover in under a minute, not at the next reminder
#: sweep.
PROVISIONING_INTERVAL_SECONDS = 45

#: An order is only retried once it has been paid for this long, so the sweep
#: never races the checkout request that is still in flight.
PROVISIONING_GRACE_SECONDS = 60

#: Usage is read back from the panels on a slower cadence than provisioning.
#: Panels cache their counters and every sweep is a round trip per node, so
#: asking more often costs traffic without producing fresher numbers.
USAGE_SYNC_INTERVAL_SECONDS = 600

#: Expiry is a date comparison, not a network call, so it can run often.
#: A service that lapsed at midnight should not still read as active at
#: nine, which is when the customer notices before we do.
EXPIRY_SWEEP_INTERVAL_SECONDS = 300

#: Guards a tick across processes. Comfortably longer than a tick should take,
#: short enough that a killed worker does not block the next one for long.
LOCK_TTL_SECONDS = 300
LOCK_KEY = "worker:tick"

#: Auto-renewal looks a day ahead, so every quarter of an hour is plenty; the
#: attempt log keeps a slow tick from charging anybody twice.
AUTO_RENEW_INTERVAL_SECONDS = 900

#: How often the worker asks whether a backup is due. The operator's interval
#: is in hours; this only decides how late within the hour it can be.
BACKUP_CHECK_INTERVAL_SECONDS = 600

#: Deleting lapsed services is housekeeping; hourly is plenty.
CLEANUP_INTERVAL_SECONDS = 3600


class Worker:
    """Runs scheduled jobs until told to stop."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._stopping = asyncio.Event()
        #: Jobs added after the three counters in `run`: name, interval, job.
        #: A table rather than a fourth hand-kept counter, the kind that was
        #: once read every tick and never written.
        self._periodic: list[tuple[str, float, Callable[[], Awaitable[None]]]] = [
            ("auto_renew", AUTO_RENEW_INTERVAL_SECONDS, self._auto_renew),
            ("backup", BACKUP_CHECK_INTERVAL_SECONDS, self._backup),
            ("cleanup", CLEANUP_INTERVAL_SECONDS, self._delete_lapsed),
        ]
        self._next_run: dict[str, float] = {}

    def request_stop(self) -> None:
        """Finish the current tick, then exit. Wired to SIGTERM and SIGINT."""
        logger.info("worker.stop_requested")
        self._stopping.set()

    async def run(self) -> None:
        logger.info("worker.started", tick_seconds=TICK_SECONDS)
        provisioning_due = 0.0
        usage_due = 0.0
        expiry_due = 0.0
        while not self._stopping.is_set():
            await self._guarded_tick(
                run_provisioning=provisioning_due <= 0,
                run_usage_sync=usage_due <= 0,
                run_expiry_sweep=expiry_due <= 0,
            )
            provisioning_due = (
                PROVISIONING_INTERVAL_SECONDS
                if provisioning_due <= 0
                else provisioning_due - TICK_SECONDS
            )
            usage_due = USAGE_SYNC_INTERVAL_SECONDS if usage_due <= 0 else usage_due - TICK_SECONDS
            # expiry_due was read every tick and never written, so the sweep ran
            # on every tick instead of every EXPIRY_SWEEP_INTERVAL_SECONDS - ten
            # times more often than intended, against the whole subscription
            # table.
            expiry_due = (
                EXPIRY_SWEEP_INTERVAL_SECONDS if expiry_due <= 0 else expiry_due - TICK_SECONDS
            )
            self._beat()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=TICK_SECONDS)
        logger.info("worker.stopped")

    def _beat(self) -> None:
        """Record that a tick just finished, for the container healthcheck.

        The healthcheck used to be `pgrep -f geekvpn.entrypoints.worker`, and
        `pgrep` is in procps, which the runtime image does not install - so the
        check errored on every run and the worker was permanently unhealthy
        while doing its job perfectly.

        A file's mtime is a better signal anyway: "a tick completed recently"
        rather than "a process exists", which stays true through a hang.
        """
        with contextlib.suppress(OSError):
            HEARTBEAT_PATH.write_text(str(time.time()), encoding="utf-8")

    async def _guarded_tick(
        self, *, run_provisioning: bool, run_usage_sync: bool, run_expiry_sweep: bool
    ) -> None:
        """Take the cross-process lock, then tick. Skip quietly if held."""
        redis = self._container.redis
        acquired = await redis.set(LOCK_KEY, "1", nx=True, ex=LOCK_TTL_SECONDS)
        if not acquired:
            logger.debug("worker.tick_skipped", reason="lock_held")
            return
        try:
            if run_provisioning:
                await self._drain_provisioning()
            if run_usage_sync:
                await self._sync_usage()
            if run_expiry_sweep:
                await self._expire_lapsed()
            await self._run_periodic()
            await self._run_scheduled_jobs()
        except Exception:
            # Never let one bad tick kill the process; the next one may succeed.
            logger.exception("worker.tick_failed")
        finally:
            with contextlib.suppress(Exception):
                await redis.delete(LOCK_KEY)

    async def _drain_provisioning(self) -> None:
        """Retry every paid order still without a service."""
        async with self._container.session_factory() as session:
            scope = build_scope(self._container, session)
            try:
                done = await scope.provisioning.drain_stuck(
                    older_than_seconds=PROVISIONING_GRACE_SECONDS
                )
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await scope.aclose()
        if done:
            logger.info("worker.provisioned", count=len(done), orders=list(done))

    async def _sync_usage(self) -> None:
        """Read traffic counters back from every sellable node.

        One batched request per node, and a node that refuses is logged and
        skipped rather than aborting the sweep - otherwise a single dead panel
        freezes the usage figures for every other node too.
        """
        async with self._container.session_factory() as session:
            scope = build_scope(self._container, session)
            try:
                report = await scope.usage_sync.sync_all()
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await scope.aclose()
        logger.info(
            "worker.usage_synced",
            updated=report.updated,
            nodes=len(report.nodes),
            failed_nodes=report.failed_nodes,
        )

    async def _expire_lapsed(self) -> None:
        """Move subscriptions past their date into EXPIRED.

        Nothing ran this before, so a service stayed ACTIVE forever once its
        date passed: the dashboard kept saying active and the renewal prompt
        never fired.
        """
        async with self._container.session_factory() as session:
            scope = build_scope(self._container, session)
            try:
                expired = await scope.provisioning.expire_lapsed()
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await scope.aclose()
        if expired:
            logger.info("worker.subscriptions_expired", count=expired)
            await self._report(AlertKind.SERVICE, EXPIRED_REPORT_FA.format(count=expired))

    async def _run_periodic(self) -> None:
        """Run each job in `_periodic` whose interval has passed.

        One job failing is logged and does not stop the others: a panel that
        refuses a renewal must not also cancel tonight's backup.
        """
        now = time.monotonic()
        for name, interval, job in self._periodic:
            if self._next_run.get(name, 0.0) > now:
                continue
            self._next_run[name] = now + interval
            try:
                await job()
            except Exception:
                logger.exception("worker.job_failed", job=name)

    async def _auto_renew(self) -> None:
        report = await build_auto_renewal(self._container).run()
        if report.examined:
            logger.info(
                "worker.auto_renewed",
                examined=report.examined,
                renewed=report.renewed,
                short=report.short,
                failed=report.failed,
            )

    async def _backup(self) -> None:
        """Send the database to the backup channel when the interval has passed.

        The last run is kept in the shared cache rather than in memory, so a
        worker restarted every few hours still backs up once a day and not on
        every start.
        """
        settings = await asyncio.to_thread(backup_settings, self._container)
        if not settings.chat_id:
            return
        cache = self._container.cache
        stamp = await cache.get(LAST_BACKUP_KEY)
        now = self._container.clock.now()
        last = datetime.fromisoformat(stamp) if stamp else None
        if not is_due(last, now=now, interval_hours=settings.interval_hours):
            return
        # Stamped before sending: a backup that fails is retried next
        # interval, not every ten minutes against a channel that refuses it.
        await cache.set(LAST_BACKUP_KEY, now.isoformat())
        await asyncio.to_thread(send_backup, self._container, settings.chat_id)

    async def _delete_lapsed(self) -> None:
        """Delete panel accounts of services that ended past the grace period."""
        async with self._container.session_factory() as session:
            scope = build_scope(self._container, session)

            async def revoke(subscription_id: str, reason_fa: str) -> object:
                revoked = await scope.subscription_admin.revoke(
                    subscription_id, reason_fa=reason_fa
                )
                # Each one committed as it goes: the panel account is already
                # gone, and a later failure must not roll the record back to
                # claim it still exists.
                await session.commit()
                return revoked

            async def hours() -> int:
                return await scope.settings_service.get(DELETE_EXPIRED_AFTER_HOURS)

            try:
                removed = await ExpiredCleanup(
                    lapsed=scope.subscriptions,
                    revoke=revoke,
                    hours=hours,
                    clock=self._container.clock,
                ).run()
            finally:
                await scope.aclose()
        if removed:
            logger.info("worker.lapsed_deleted", count=len(removed))
            await self._report_cleanup(removed)

    async def _report_cleanup(self, removed: list[Any]) -> None:
        names = ", ".join(sub.remote_username for sub in removed[:30])
        more = f" (+{len(removed) - 30})" if len(removed) > 30 else ""
        await self._report(
            AlertKind.SERVICE, CLEANUP_REPORT_FA.format(count=len(removed), names=names + more)
        )

    async def _report(self, kind: AlertKind, text: str) -> None:
        def work() -> None:
            with self._container.sync_sessions() as session:
                build_sync_scope(self._container, session).operator_reports.send(kind, text)

        await asyncio.to_thread(work)

    async def _run_scheduled_jobs(self) -> None:
        """Hand the due jobs to the notification scheduler.

        Runs in a thread: these services are synchronous by design (they share
        the payment scope's session), and blocking the event loop on them would
        stall the provisioning drain behind a broadcast.
        """
        report = await asyncio.to_thread(self._tick_sync)
        for run in report.failures():
            logger.error("worker.job_failed", job=str(run.job), error=str(run.error))
        for run in report.ran():
            logger.info("worker.job_ran", job=str(run.job))

    def _dispatch_broadcasts(self) -> None:
        """Send every scheduled broadcast whose time has come, per shop.

        Each one gets its own scope, built for the shop that composed it, so a
        reseller's announcement resolves over their customers and goes out
        through their bot. One scope for all of them would send every shop's
        message from ours, to an audience drawn from everybody.

        A shop that fails must not strand the others, so each is caught: the
        aggregate records its own failure and the next tick tries again.
        """
        with self._container.sync_sessions() as session:
            scope = build_sync_scope(self._container, session)
            due = scope.broadcasts.due(self._container.clock.now(), limit=_BROADCAST_BATCH)
            shops = {broadcast.id: scope.broadcasts.shop_of(broadcast.id) for broadcast in due}

        for broadcast_id, reseller_id in shops.items():
            with self._container.sync_sessions() as session:
                shop = build_sync_scope(self._container, session, reseller_id=reseller_id)
                try:
                    shop.broadcast_service.send_now(broadcast_id)
                    session.commit()
                except Exception:
                    session.rollback()
                    logger.exception(
                        "worker.broadcast_failed",
                        broadcast_id=broadcast_id,
                        reseller=str(reseller_id) if reseller_id else None,
                    )

    def _shops(self) -> list[uuid.UUID | None]:
        """Every shop whose customers can be written to, ours first.

        Only resellers with a bot token: their customers have never started
        ours, and a shop with no bot of its own has no way to reach them at
        all, so sweeping it would queue messages nothing can deliver.
        """
        with self._container.sync_sessions() as session:
            rows = session.execute(
                select(ResellerModel.id).where(ResellerModel.bot_token_encrypted.is_not(None))
            )
            return [None, *rows.scalars().all()]

    def _tick_sync(self) -> TickReport:
        """Run the customer-facing sweeps once for every shop.

        They used to run once, against an unscoped reader, through whichever
        bot the platform scope held. So a reseller's customer either heard
        nothing or heard from a bot they have never spoken to - which Telegram
        refuses, and which is then recorded as a suppression indistinguishable
        from somebody blocking us.

        `DEFERRED_FLUSH` and `BROADCAST_DISPATCH` stay on the platform pass.
        The first walks the queue, whose rows already carry their own shop; the
        second does its own per-shop loop for the same reason this one exists.
        """
        report: TickReport | None = None
        for reseller_id in self._shops():
            try:
                one = self._tick_shop(reseller_id)
            except Exception:
                # A shop with a bad token or a broken row must not stop the
                # others: the next tick tries it again.
                logger.exception(
                    "worker.shop_tick_failed",
                    reseller=str(reseller_id) if reseller_id else None,
                )
                continue
            if report is None:
                report = one
            else:
                report.runs.extend(one.runs)
        return report or TickReport(at=self._container.clock.now())

    def _tick_shop(self, reseller_id: uuid.UUID | None) -> TickReport:
        with self._container.sync_sessions() as session:
            scope = build_sync_scope(self._container, session, reseller_id=reseller_id)
            scheduler = NotificationScheduler(clock=self._container.clock)
            scheduler.register(
                JobKind.EXPIRATION_REMINDER, scope.reminders.run_expiration_reminders
            )
            scheduler.register(JobKind.TRAFFIC_REMINDER, scope.reminders.run_traffic_reminders)
            scheduler.register(JobKind.IDLE_NUDGE, scope.reminders.run_idle_nudges)
            scheduler.register(JobKind.DEFERRED_FLUSH, scope.engine.flush_deferred)
            # BROADCAST_DISPATCH is registered now. The comment that used to
            # sit here said `BroadcastService` needed a reader with no SQL
            # implementation - `SqlAudienceResolver` exists, so that gap has
            # been closed for a while and scheduled broadcasts were still never
            # firing because nothing had come back to remove the note.
            #
            # CAMPAIGN_ANNOUNCE stays unregistered, for the reason that is
            # still true of it.
            if reseller_id is None:
                scheduler.register(JobKind.BROADCAST_DISPATCH, self._dispatch_broadcasts)
            try:
                report = scheduler.tick()
                session.commit()
                return report
            except Exception:
                session.rollback()
                raise


async def _main(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    configure_logging(
        level=settings.logging.level,
        json_output=settings.logging.json,
        redact_keys=settings.logging.redact_keys,
        service=f"{settings.app.name}-worker",
    )
    container = build_container(settings)
    worker = Worker(container)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    try:
        await worker.run()
    finally:
        await close_container(container)


def main() -> None:
    """Console entrypoint: ``python -m geekvpn.entrypoints.worker``."""
    asyncio.run(_main())


def _handle_signal(signum: int, frame: FrameType | None) -> None:  # pragma: no cover
    """Fallback for platforms without ``loop.add_signal_handler``."""
    raise KeyboardInterrupt


if __name__ == "__main__":
    main()

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
from types import FrameType

from geekvpn.application.notifications.scheduler import NotificationScheduler, TickReport
from geekvpn.domain.notifications.enums import JobKind
from geekvpn.infrastructure.config.settings import Settings, get_settings
from geekvpn.infrastructure.di.container import Container, build_container, close_container
from geekvpn.infrastructure.di.scope import build_scope
from geekvpn.infrastructure.di.sync_scope import build_sync_scope
from geekvpn.infrastructure.logging.setup import configure_logging, get_logger

logger = get_logger(__name__)

#: How often the loop wakes. The scheduler decides what is actually due, so this
#: is a resolution, not a job interval.
TICK_SECONDS = 30

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


class Worker:
    """Runs scheduled jobs until told to stop."""

    def __init__(self, container: Container) -> None:
        self._container = container
        self._stopping = asyncio.Event()

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
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._stopping.wait(), timeout=TICK_SECONDS)
        logger.info("worker.stopped")

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

    def _tick_sync(self) -> TickReport:
        with self._container.sync_sessions() as session:
            scope = build_sync_scope(self._container, session)
            scheduler = NotificationScheduler(clock=self._container.clock)
            scheduler.register(
                JobKind.EXPIRATION_REMINDER, scope.reminders.run_expiration_reminders
            )
            scheduler.register(JobKind.TRAFFIC_REMINDER, scope.reminders.run_traffic_reminders)
            scheduler.register(JobKind.DEFERRED_FLUSH, scope.engine.flush_deferred)
            # BROADCAST_DISPATCH and CAMPAIGN_ANNOUNCE are deliberately not
            # registered yet: BroadcastService and CampaignService each need a
            # reader that has no SQL implementation, and registering a handler
            # that cannot be built would turn a known gap into a tick that
            # fails every 30 seconds. The scheduler skips unregistered jobs.
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

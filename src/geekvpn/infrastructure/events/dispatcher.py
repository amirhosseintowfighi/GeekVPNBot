"""The event dispatcher.

Until now the only ``EventPublisher`` in the codebase wrote events to the log
and stopped. That made two whole features inert without anything looking broken:
``application.notifications.subscribers.register()`` built a dispatch table
nobody consumed, and ``PaymentApproved`` - documented in the payment domain as
"the single trigger for provisioning" - triggered nothing.

This class is the missing consumer.

Three rules, and each one is load-bearing:

**A handler never fails the operation.** An event describes something that has
*already* happened. Letting a Telegram outage roll back an approved payment
would be trading a real, captured, correct transaction for a cosmetic one. Every
handler is wrapped; failures are logged with the event name and moved past.

**Events are routed by wire name, not by class.** ``PaymentApproved.name`` is
``"billing.payment.approved.v1"``. Keying on the string means the day these
events arrive from an outbox table as decoded JSON, the same table routes them
with no importing of the payment domain and no changes here.

**Unknown events are logged, not dropped silently.** A new event with no
subscriber is normal; an event that was *supposed* to have one and does not is a
bug, and the only way to tell them apart later is a log line that names the
event.

Ordering note: handlers run inline, inside the caller's transaction. That is
deliberate for now - the order must move to PAID in the same transaction that
approved the payment, and an out-of-process bus cannot offer that. Handlers that
touch the outside world (Telegram) are the ones that must tolerate being called
inside a transaction, which is why they return results instead of raising.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from geekvpn.infrastructure.logging.setup import get_logger

logger = get_logger(__name__)

Handler = Callable[[Any], Any]


def event_name(event: object) -> str:
    """The wire name of an event, falling back to its class name."""
    return str(getattr(type(event), "name", type(event).__name__))


class DispatchingEventPublisher:
    """Routes domain events to the handlers registered for them."""

    __slots__ = ("_handlers", "_log_all")

    def __init__(
        self,
        handlers: Mapping[str, Handler] | None = None,
        *,
        log_all: bool = True,
    ) -> None:
        """
        :param handlers: event wire name -> callable taking the event.
        :param log_all: also emit the structured ``domain.event`` line for every
            event, handled or not. Kept on by default: the log is how "what
            happened to this payment?" is answered in production, and a handled
            event is not less interesting than an unhandled one.
        """
        self._handlers: dict[str, list[Handler]] = {}
        for name, handler in (handlers or {}).items():
            self._handlers.setdefault(name, []).append(handler)
        self._log_all = log_all

    def subscribe(self, name: str, handler: Handler) -> None:
        """Add a handler for one event name. Multiple handlers are allowed and
        run in registration order."""
        self._handlers.setdefault(name, []).append(handler)

    def handlers_for(self, name: str) -> tuple[Handler, ...]:
        return tuple(self._handlers.get(name, ()))

    def publish_all(self, events: Iterable[object]) -> None:
        """Deliver every event. Never raises."""
        for event in events:
            name = event_name(event)
            if self._log_all:
                self._log(event, name)

            handlers = self._handlers.get(name)
            if not handlers:
                logger.debug("domain.event_unhandled", event_type=name)
                continue

            for handler in handlers:
                try:
                    handler(event)
                except Exception:  # pragma: no cover - defensive by design
                    # Deliberately broad. The alternative is that one broken
                    # subscriber can undo a captured payment.
                    logger.exception(
                        "domain.event_handler_failed",
                        event_type=name,
                        handler=getattr(handler, "__qualname__", repr(handler)),
                    )

    def _log(self, event: object, name: str) -> None:
        try:
            payload = event.payload() if hasattr(event, "payload") else {}
            logger.info("domain.event", event_type=name, payload=payload)
        except Exception:  # pragma: no cover
            logger.warning("domain.event_unloggable", event_type=name)


__all__ = ["DispatchingEventPublisher", "Handler", "event_name"]

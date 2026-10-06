"""A message some hours after a customer took the free trial.

The trial has been tried and nothing bought yet: the moment a shop most wants
a word. The operator writes it and picks the wait; the worker runs this every
hour, for every shop, through that shop's own bot.

Once per customer: the engine's dedupe key carries that, so nothing here
remembers who was told. The window has a floor, so switching it on does not
message everyone who ever took a trial.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta

from geekvpn.application.ports.clock import Clock

_log = logging.getLogger(__name__)

DEDUPE_KEY = "trial.followup"
LOOKBACK = timedelta(days=3)


class TrialFollowUp:
    def __init__(
        self,
        *,
        #: Customers whose trial was placed in ``[after, before)`` and who
        #: have bought nothing since.
        candidates: Callable[[datetime, datetime], Sequence[int]],
        #: Whether the message went out; a duplicate or a muted customer is no.
        send: Callable[[int, str], bool],
        clock: Clock,
    ) -> None:
        self._candidates = candidates
        self._send = send
        self._clock = clock

    def run(self, *, after_hours: int, message_fa: str) -> int:
        """Send to everyone due. Returns how many it reached."""
        if after_hours <= 0 or not message_fa.strip():
            return 0
        before = self._clock.now() - timedelta(hours=after_hours)
        reached = 0
        for user_id in self._candidates(before - LOOKBACK, before):
            try:
                if self._send(user_id, message_fa):
                    reached += 1
            except Exception:
                _log.warning("trial_followup.not_sent user=%s", user_id, exc_info=True)
        return reached


__all__ = ["DEDUPE_KEY", "LOOKBACK", "TrialFollowUp"]

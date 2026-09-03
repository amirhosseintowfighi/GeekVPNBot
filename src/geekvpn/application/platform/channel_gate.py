"""Which required channels a customer has not joined yet.

The rule is one line - every active channel, or the bot does not serve them -
and it is here rather than in the middleware so it can be tested without a
Telegram account, a bot token, or a network.

Two decisions are load-bearing.

**A channel we cannot check does not block anybody.** Telegram refuses
`getChatMember` when the bot is not an administrator of the channel, and it
fails outright when the channel is gone. Treating either as "not joined" locks
every customer out of a working shop over a misconfiguration they cannot see or
fix. The requirement is dropped and the failure is the operator's to notice.

**Membership is cached only when it passes.** A customer who has joined is
still joined a minute later, and re-asking Telegram on every button press is a
round trip per channel per tap. A customer who has *not* joined is about to
join, and caching that would leave them staring at a gate they have already
satisfied.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RequiredChannel:
    """One channel a shop demands membership of."""

    id: str
    #: `@name` or `-100...`, whichever the operator gave us.
    chat_ref: str
    title_fa: str
    invite_url: str | None = None

    @property
    def url(self) -> str | None:
        """Where the join button should send somebody.

        An explicit invite link wins: a private channel has no `@name` to open,
        and a public one given by numeric id has nothing to build a link from
        either. `None` means we cannot offer a button, only the name.
        """
        if self.invite_url:
            return self.invite_url
        if self.chat_ref.startswith("@"):
            return f"https://t.me/{self.chat_ref[1:]}"
        return None


#: Answers "is this person in that chat". `None` means the question could not be
#: asked - the bot is not an administrator there, or the channel is gone - which
#: is deliberately different from `False`.
MembershipCheck = Callable[[str, int], Awaitable[bool | None]]


async def missing_channels(
    channels: Sequence[RequiredChannel],
    *,
    telegram_id: int,
    is_member: MembershipCheck,
) -> list[RequiredChannel]:
    """The subset this person still has to join.

    Empty means they may use the bot. A channel that cannot be checked is not
    in the result: see the module docstring for why a misconfiguration must not
    become a lockout.
    """
    missing: list[RequiredChannel] = []
    for channel in channels:
        joined = await is_member(channel.chat_ref, telegram_id)
        if joined is False:
            missing.append(channel)
    return missing


__all__ = ["MembershipCheck", "RequiredChannel", "missing_channels"]

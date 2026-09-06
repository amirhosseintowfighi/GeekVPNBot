"""Where a subscription link points, as opposed to where the panel says it does.

A panel builds subscription URLs from the base URL it was configured with. On
a split setup that is the API host - `panel.doping.games:8443` - while what the
customer must open is `panel2.hostcheap.top`. Handing them the panel's own
answer gives them a link to a host that does not serve them, and the failure
looks exactly like a broken service.

So a node may declare the host its links are really served on, and everything
we store or show is rebuilt onto it. Path and query are kept verbatim: the
token is the account, and rewriting anything but the origin would break it.

The same field answers a second question. When somebody pastes a link to be
adopted, its host names the panel it came from - which matters as soon as two
panels each hold an account called `amir`, because then the username is not an
answer and only the token and the host are.
"""

from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def host_of(url: str) -> str:
    """The `host:port` of a URL, lowercased, or `""` if it has none."""
    if not url:
        return ""
    parsed = urlsplit(url.strip())
    if not parsed.netloc and "://" not in url:
        # A bare `panel.example.com/sub/x` parses as all-path. Retrying with a
        # scheme is cheaper than telling an operator their entry was ignored.
        parsed = urlsplit(f"//{url.strip()}")
    return parsed.netloc.lower()


def public_link(url: str | None, base: str | None) -> str | None:
    """`url` rebuilt on `base`, keeping its path and query.

    Returns `url` unchanged when the node declares no separate host, when the
    link has no host of its own to replace, or when the base is unusable - a
    misconfigured field must degrade to the panel's own answer, never to a
    link with no host at all.
    """
    if not url or not base:
        return url
    parsed = urlsplit(url.strip())
    if not parsed.netloc:
        return url
    target = urlsplit(base.strip() if "://" in base else f"https://{base.strip()}")
    if not target.netloc:
        return url
    return urlunsplit(
        (target.scheme or parsed.scheme, target.netloc, parsed.path, parsed.query, "")
    )


__all__ = ["host_of", "public_link"]

"""Firebase Cloud Messaging, HTTP v1, without the Firebase Admin SDK.

The v1 API wants an OAuth2 access token for the project's service account.
That token comes from Google's token endpoint in exchange for a JWT the
service account signs with its own key (RS256), which `pyjwt` and
`cryptography` already in the dependencies can do. One token lasts an hour and
is reused until shortly before it expires.

Sends are synchronous: the callers are the synchronous support services, and
each send is one small request with a short timeout.
"""

from __future__ import annotations

import base64
import binascii
import enum
import json
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
import structlog

logger = structlog.stdlib.get_logger(__name__)

_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - a URL, not a secret
#: Renew the access token this long before Google says it expires.
_TOKEN_SLACK_SECONDS = 300


class SendOutcome(enum.Enum):
    SENT = "sent"
    #: The app was uninstalled or the token rotated: forget the token.
    UNREGISTERED = "unregistered"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ServiceAccount:
    project_id: str
    client_email: str
    private_key: str

    @classmethod
    def parse(cls, raw: str) -> ServiceAccount | None:
        """The console's JSON key, as JSON or as base64 of it; None when unusable."""
        text = raw.strip()
        if not text:
            return None
        if not text.startswith("{"):
            try:
                text = base64.b64decode(text, validate=True).decode("utf-8")
            except (binascii.Error, UnicodeDecodeError):
                return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        try:
            return cls(
                project_id=str(data["project_id"]),
                client_email=str(data["client_email"]),
                private_key=str(data["private_key"]),
            )
        except KeyError:
            return None


class FcmClient:
    """Sends data messages to app tokens. Thread-safe; share one per process."""

    def __init__(self, account: ServiceAccount, *, timeout: float = 5.0) -> None:
        self._account = account
        self._timeout = timeout
        self._lock = threading.Lock()
        self._access_token = ""
        self._expires_at = 0.0

    @property
    def project_id(self) -> str:
        return self._account.project_id

    def send(self, token: str, data: dict[str, str]) -> SendOutcome:
        """A data-only, high-priority message: the app draws the notification itself.

        Data-only so the app can route a tap (to the ticket, say) whether it
        was in the foreground or not; a notification payload would be drawn by
        the system and open the launcher instead.
        """
        body: dict[str, Any] = {
            "message": {
                "token": token,
                "data": data,
                "android": {"priority": "high"},
            }
        }
        url = f"https://fcm.googleapis.com/v1/projects/{self._account.project_id}/messages:send"
        try:
            access = self._token()
            response = httpx.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {access}"},
                timeout=self._timeout,
            )
        except (httpx.HTTPError, jwt.PyJWTError, ValueError) as exc:
            logger.warning("push.fcm_error", error=type(exc).__name__)
            return SendOutcome.FAILED
        if response.status_code == 200:
            return SendOutcome.SENT
        if response.status_code == 404 or "UNREGISTERED" in response.text:
            return SendOutcome.UNREGISTERED
        logger.warning("push.fcm_rejected", status=response.status_code)
        return SendOutcome.FAILED

    def _token(self) -> str:
        with self._lock:
            now = time.time()
            if self._access_token and now < self._expires_at - _TOKEN_SLACK_SECONDS:
                return self._access_token
            assertion = jwt.encode(
                {
                    "iss": self._account.client_email,
                    "scope": _SCOPE,
                    "aud": _TOKEN_URL,
                    "iat": int(now),
                    "exp": int(now) + 3600,
                },
                self._account.private_key,
                algorithm="RS256",
            )
            response = httpx.post(
                _TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=self._timeout,
            )
            response.raise_for_status()
            payload = response.json()
            self._access_token = str(payload["access_token"])
            self._expires_at = now + float(payload.get("expires_in", 3600))
            return self._access_token

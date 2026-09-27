"""Typed, audited access to runtime settings.

Every setting is *declared* first. An undeclared key cannot be written, so the
settings table can never silently accumulate typos like `maintenence_mode`,
and the admin panel can render a form from the registry instead of a raw
key/value grid.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.settings_store import SettingRecord, SettingsStore
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError, ValidationError
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.permissions import Permission

T = TypeVar("T", bound=bool | int | float | str | list[Any] | dict[str, Any])


@dataclass(frozen=True, slots=True)
class SettingDefinition[T: bool | int | float | str | list[Any] | dict[str, Any]]:
    """A declared, typed runtime setting."""

    key: str
    default: T
    type_: type
    description: str
    #: What the operator sees. `description` is English and for us; the panel
    #: is Persian and for them, and it used to invent a label client-side from
    #: a field the API never sent - so every row rendered blank.
    label_fa: str = ""
    is_secret: bool = False
    write_permission: Permission = Permission.SETTINGS_WRITE
    #: Lowest accepted number. A negative trial size or a zero-day warning is
    #: not a preference, it is a typo that would surface at the customer.
    minimum: int | None = None

    @property
    def kind(self) -> str:
        """How the panel should render this one.

        Derived from the declared type rather than declared separately: a
        second field would be one more thing to get out of step, and it was
        exactly that mismatch - a client guessing at `kind` - that turned every
        text setting into a numeric box that reduced it to zero on edit.
        """
        if self.type_ is bool:
            return "boolean"
        if self.type_ is int and self.key.endswith("_toman"):
            return "toman"
        if self.type_ in (int, float):
            return "number"
        return "text"

    def coerce(self, raw: Any) -> T:
        """Validate on the way in, not on the way out.

        A bad value written today must fail today, not at 2am when the code
        that reads it finally runs.
        """
        if self.type_ is bool and isinstance(raw, str):
            lowered = raw.strip().lower()
            if lowered in {"true", "1", "yes", "on"}:
                return True  # type: ignore[return-value]
            if lowered in {"false", "0", "no", "off"}:
                return False  # type: ignore[return-value]
            raise ValidationError(f"{self.key} must be a boolean.", key=self.key)
        if self.type_ is float and isinstance(raw, int):
            return float(raw)  # type: ignore[return-value]
        if not isinstance(raw, self.type_) or (self.type_ is int and isinstance(raw, bool)):
            raise ValidationError(
                f"{self.key} must be of type {self.type_.__name__}.",
                key=self.key,
                expected=self.type_.__name__,
            )
        if self.minimum is not None and isinstance(raw, int | float) and raw < self.minimum:
            raise ValidationError(
                f"{self.key} must be at least {self.minimum}.",
                key=self.key,
                minimum=self.minimum,
            )
        return raw  # type: ignore[return-value]


# --------------------------------------------------------------------------
# The registry. Adding a setting is one line here; nothing else changes.
# --------------------------------------------------------------------------

MAINTENANCE_MODE = SettingDefinition[bool](
    key="platform.maintenance_mode",
    label_fa="حالت تعمیرات",
    default=False,
    type_=bool,
    description="Reject customer traffic with a friendly Persian notice.",
)
MAINTENANCE_MESSAGE = SettingDefinition[str](
    key="platform.maintenance_message",
    label_fa="پیام حالت تعمیرات",
    default="سرویس موقتاً در حال به‌روزرسانیه. تا چند دقیقهٔ دیگه برمی‌گردیم.",
    type_=str,
    description="Message shown to customers while maintenance mode is on.",
)
REGISTRATION_ENABLED = SettingDefinition[bool](
    key="identity.registration_enabled",
    label_fa="ثبت‌نام کاربر جدید",
    default=True,
    type_=bool,
    description="Allow brand-new Telegram users to create an account.",
)
ADMIN_SESSION_IP_PINNING = SettingDefinition[bool](
    key="security.admin_session_ip_pinning",
    label_fa="بستن نشست ادمین به IP",
    default=False,
    type_=bool,
    description="Invalidate an admin session if its source IP changes.",
)
SUPPORT_TELEGRAM_HANDLE = SettingDefinition[str](
    key="support.telegram_handle",
    label_fa="آیدی پشتیبانی",
    default="@GeekVPNSupport",
    type_=str,
    description="Handle shown in bot and Mini App support screens.",
)
SUPPORT_HOURS = SettingDefinition[str](
    key="support.hours",
    label_fa="ساعات پاسخگویی",
    default="۹ صبح تا ۱۲ شب، هفت روز هفته",
    type_=str,
    description="Human-readable support hours, in Persian.",
)

#: What the payment buttons say.
#:
#: The label used to be a constant on each adapter class, so renaming "کارت به
#: کارت" meant a deployment. These are the two methods with no row of their own
#: to hang a name on - an online gateway carries its label on its account row,
#: because a shop may have several and each wants its own.
#:
#: Empty means the adapter's own name, which is what every shop gets until
#: somebody decides otherwise.
CARD_LABEL_FA = SettingDefinition[str](
    key="payments.label.card_fa",
    label_fa="نام دکمهٔ کارت به کارت",
    default="",
    type_=str,
    description="Overrides the card-to-card button's label. Empty keeps the default.",
)
CRYPTO_LABEL_FA = SettingDefinition[str](
    key="payments.label.crypto_fa",
    label_fa="نام دکمهٔ رمزارز",
    default="",
    type_=str,
    description="Overrides the crypto button's label. Empty keeps the default.",
)
SIGNUP_BONUS_TOMAN = SettingDefinition[int](
    key="wallet.signup_bonus_toman",
    label_fa="هدیهٔ کاربر جدید (تومان)",
    default=0,
    type_=int,
    description=(
        "Credit given to a customer's wallet the first time they start the bot,"
        " in Toman. Zero turns it off."
    ),
)
SIGNUP_BONUS_NOTE_FA = SettingDefinition[str](
    key="wallet.signup_bonus_note_fa",
    label_fa="متن هدیهٔ کاربر جدید",
    default="هدیهٔ خوش‌آمدگویی",
    type_=str,
    description="What the customer sees beside this credit in their wallet history.",
)

#: The free trial. It used to be constants in `free_trial.py`, so an operator
#: who wanted a bigger test, or none at all, needed a deployment.
TRIAL_ENABLED = SettingDefinition[bool](
    key="trial.enabled",
    label_fa="اکانت تست رایگان",
    default=True,
    type_=bool,
    description="Offer the one-time free trial in the bot and the Mini App.",
)
TRIAL_TRAFFIC_MIB = SettingDefinition[int](
    key="trial.traffic_mib",
    label_fa="حجم اکانت تست (مگابایت)",
    default=50,
    type_=int,
    minimum=1,
    description="Traffic each trial service gets, in MiB.",
)
TRIAL_DURATION_DAYS = SettingDefinition[int](
    key="trial.duration_days",
    label_fa="مدت اکانت تست (روز)",
    default=2,
    type_=int,
    minimum=1,
    description="How long a trial service lasts, in days.",
)
TRIAL_INTRO_FA = SettingDefinition[str](
    key="trial.intro_fa",
    label_fa="متن دکمهٔ دریافت اکانت تست",
    default="",
    type_=str,
    description="Shown when the customer taps the trial button. Empty uses the built-in text.",
)
TRIAL_AFTER_MESSAGE_FA = SettingDefinition[str](
    key="trial.after_message_fa",
    label_fa="پیام بعد از دریافت اکانت تست",
    default="",
    type_=str,
    description="Sent after the trial is delivered. Empty sends nothing extra.",
)

AUTO_RENEW_ENABLED = SettingDefinition[bool](
    key="renewal.auto_enabled",
    label_fa="تمدید خودکار از کیف پول",
    default=True,
    type_=bool,
    description=(
        "Let customers turn on renewal from their wallet. Off hides the switch"
        " and stops every pending auto-renewal."
    ),
)

#: Where operator alerts go. Zero means the private chat of every admin who
#: linked Telegram, which is what every shop had before these existed. A group
#: id (negative) sends there instead, so any admin in the group can act on a
#: receipt while the owner is asleep, and a busy shop can keep receipts from
#: drowning its tickets.
ALERTS_RECEIPTS_CHAT = SettingDefinition[int](
    key="alerts.receipts_chat_id",
    label_fa="گروه رسیدهای کارت به کارت (آیدی عددی)",
    default=0,
    type_=int,
    description="Chat id that receives receipts to approve. 0 sends to each admin privately.",
)
ALERTS_PAYMENTS_CHAT = SettingDefinition[int](
    key="alerts.payments_chat_id",
    label_fa="گروه سایر واریزی‌ها (آیدی عددی)",
    default=0,
    type_=int,
    description="Chat id for crypto proofs. 0 uses the receipts group.",
)
ALERTS_TICKETS_CHAT = SettingDefinition[int](
    key="alerts.tickets_chat_id",
    label_fa="گروه تیکت‌ها (آیدی عددی)",
    default=0,
    type_=int,
    description="Chat id told about new tickets and customer replies. 0 sends to each admin.",
)
ALERTS_REPORTS_CHAT = SettingDefinition[int](
    key="alerts.reports_chat_id",
    label_fa="گروه گزارش‌ها (آیدی عددی)",
    default=0,
    type_=int,
    description=(
        "Chat id for reports: purchases, renewals, transfers, renames. 0 sends to each admin."
    ),
)

RENAME_ENABLED = SettingDefinition[bool](
    key="services.rename_enabled",
    label_fa="تغییر نام سرویس توسط کاربر",
    default=True,
    type_=bool,
    description="Let customers give their services a name of their own in the bot.",
)
TRANSFER_ENABLED = SettingDefinition[bool](
    key="services.transfer_enabled",
    label_fa="انتقال سرویس به کاربر دیگر",
    default=True,
    type_=bool,
    description="Let customers hand a service to another customer of this shop.",
)

SETTING_REGISTRY: dict[str, SettingDefinition[Any]] = {
    definition.key: definition
    for definition in (
        MAINTENANCE_MODE,
        MAINTENANCE_MESSAGE,
        REGISTRATION_ENABLED,
        ADMIN_SESSION_IP_PINNING,
        SUPPORT_TELEGRAM_HANDLE,
        SUPPORT_HOURS,
        SIGNUP_BONUS_TOMAN,
        SIGNUP_BONUS_NOTE_FA,
        CARD_LABEL_FA,
        CRYPTO_LABEL_FA,
        TRIAL_ENABLED,
        TRIAL_TRAFFIC_MIB,
        TRIAL_DURATION_DAYS,
        TRIAL_INTRO_FA,
        TRIAL_AFTER_MESSAGE_FA,
        AUTO_RENEW_ENABLED,
        ALERTS_RECEIPTS_CHAT,
        ALERTS_PAYMENTS_CHAT,
        ALERTS_TICKETS_CHAT,
        ALERTS_REPORTS_CHAT,
        RENAME_ENABLED,
        TRANSFER_ENABLED,
    )
}


class SettingsService:
    def __init__(self, *, store: SettingsStore, audit: AuditRecorder) -> None:
        self._store = store
        self._audit = audit

    async def get(self, definition: SettingDefinition[T]) -> T:
        """Read a setting, falling back to its declared default.

        A missing or corrupt row returns the default rather than raising: a
        settings table problem must not take the platform down.
        """
        record = await self._store.get(definition.key)
        if record is None:
            return definition.default
        try:
            return definition.coerce(record.value)
        except ValidationError:
            return definition.default

    async def list_all(self) -> Sequence[SettingRecord]:
        """Every declared setting, with its effective value."""
        stored = {record.key: record for record in await self._store.all()}
        return [
            stored.get(
                definition.key,
                SettingRecord(
                    key=definition.key,
                    value=definition.default,
                    description=definition.description,
                    is_secret=definition.is_secret,
                ),
            )
            for definition in SETTING_REGISTRY.values()
        ]

    async def set(
        self, key: str, value: Any, *, actor_id: uuid.UUID, actor_label: str | None = None
    ) -> SettingRecord:
        definition = SETTING_REGISTRY.get(key)
        if definition is None:
            raise NotFoundError("Unknown setting.", key=key)

        coerced = definition.coerce(value)
        previous = await self._store.get(key)
        record = await self._store.set(
            key,
            coerced,
            updated_by=actor_id,
            description=definition.description,
            is_secret=definition.is_secret,
        )
        await self._audit.record(
            AuditAction.SETTING_CHANGED,
            actor_type=SubjectType.ADMIN,
            actor_id=actor_id,
            actor_label=actor_label,
            target_type="setting",
            target_id=key,
            previous="***" if definition.is_secret else (previous.value if previous else None),
            new="***" if definition.is_secret else coerced,
        )
        return record

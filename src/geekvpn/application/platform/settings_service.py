"""Typed, audited access to runtime settings.

Every setting is *declared* first. An undeclared key cannot be written, so the
settings table can never silently accumulate typos like `maintenence_mode`,
and the admin panel can render a form from the registry instead of a raw
key/value grid.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, TypeVar

from geekvpn.application.catalog.policy_provider import (
    KEY_REFERRAL_ENABLED,
    KEY_REFERRAL_FIRST_BPS,
    KEY_REFERRAL_FIRST_FIXED,
    KEY_REFERRAL_INVITEE_BONUS,
    KEY_REFERRAL_RECURRING_BPS,
    KEY_REFERRAL_RECURRING_FIXED,
)
from geekvpn.application.ports.audit import AuditRecorder
from geekvpn.application.ports.settings_store import SettingRecord, SettingsStore
from geekvpn.domain.audit.entry import AuditAction
from geekvpn.domain.base.errors import NotFoundError, ValidationError
from geekvpn.domain.identity.enums import SubjectType
from geekvpn.domain.identity.permissions import Permission
from geekvpn.domain.notifications.schedule import parse_thresholds
from geekvpn.domain.payments.wallet import MAX_TOPUP, MIN_TOPUP

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
    #: Highest accepted number.
    maximum: int | None = None
    #: Extra check for a text setting with a shape, e.g. "7,3,1". Returns an
    #: English reason when the value is wrong, None when it is fine.
    validator: Callable[[Any], str | None] | None = None
    #: How the panel renders it when the key's spelling cannot say so: a
    #: pricing key keeps the name the pricing engine already reads.
    render_as: str | None = None

    @property
    def kind(self) -> str:
        """How the panel should render this one.

        Derived from the declared type rather than declared separately: a
        second field would be one more thing to get out of step, and it was
        exactly that mismatch - a client guessing at `kind` - that turned every
        text setting into a numeric box that reduced it to zero on edit.
        """
        if self.render_as is not None:
            return self.render_as
        if self.type_ is bool:
            return "boolean"
        if self.type_ is dict:
            # Edited from the bot's admin menu, one screen at a time; a form
            # field could only show it as a blob.
            return "map"
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
        if self.maximum is not None and isinstance(raw, int | float) and raw > self.maximum:
            raise ValidationError(
                f"{self.key} must be at most {self.maximum}.",
                key=self.key,
                maximum=self.maximum,
            )
        if self.validator is not None:
            problem = self.validator(raw)
            if problem:
                raise ValidationError(f"{self.key}: {problem}", key=self.key)
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

ALERTS_SERVICES_CHAT = SettingDefinition[int](
    key="alerts.services_chat_id",
    label_fa="کانال اعلان حذف و اتمام سرویس‌ها (آیدی عددی)",
    default=0,
    type_=int,
    description="Chat told when services expire or are deleted. 0 uses the reports chat.",
)
ALERTS_TRIALS_CHAT = SettingDefinition[int](
    key="alerts.trials_chat_id",
    label_fa="کانال اکانت‌های تست (آیدی عددی)",
    default=0,
    type_=int,
    description="Chat told about every free trial handed out. 0 uses the reports chat.",
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

BACKUP_CHAT = SettingDefinition[int](
    key="backup.chat_id",
    label_fa="کانال بکاپ دیتابیس (آیدی عددی)",
    default=0,
    type_=int,
    description=(
        "Chat the database backup is sent to, as a zip. 0 turns automatic backups off."
        " The bot must be an admin of the channel."
    ),
)
BACKUP_INTERVAL_HOURS = SettingDefinition[int](
    key="backup.interval_hours",
    label_fa="فاصلهٔ بکاپ خودکار (ساعت)",
    default=24,
    type_=int,
    minimum=1,
    description="How often the automatic backup runs, in hours.",
)

#: Top-up limits, inside the hard bounds the wallet itself enforces. The
#: defaults are those bounds, so a shop that never touches them sees no change.
TOPUP_MIN_TOMAN = SettingDefinition[int](
    key="wallet.topup_min_toman",
    label_fa="حداقل مبلغ شارژ کیف پول (تومان)",
    default=MIN_TOPUP,
    type_=int,
    minimum=MIN_TOPUP,
    maximum=MAX_TOPUP,
    description="Smallest wallet top-up a customer may start, in Toman.",
)
TOPUP_MAX_TOMAN = SettingDefinition[int](
    key="wallet.topup_max_toman",
    label_fa="سقف مبلغ شارژ کیف پول (تومان)",
    default=MAX_TOPUP,
    type_=int,
    minimum=MIN_TOPUP,
    maximum=MAX_TOPUP,
    description="Largest wallet top-up a customer may start, in Toman.",
)


def _days_list(raw: Any) -> str | None:
    return None if parse_thresholds(raw, low=1, high=60) else "use days like 7,3,1"


def _percent_list(raw: Any) -> str | None:
    return None if parse_thresholds(raw, low=1, high=99) else "use percents like 80,95"


REMINDER_EXPIRY_DAYS = SettingDefinition[str](
    key="reminders.expiry_days",
    label_fa="اخطار انقضا چند روز قبل (مثلاً ۷,۳,۱)",
    default="7,3,1",
    type_=str,
    validator=_days_list,
    description="Days before expiry at which the customer is warned, comma separated.",
)
REMINDER_TRAFFIC_PERCENTS = SettingDefinition[str](
    key="reminders.traffic_percents",
    label_fa="اخطار حجم در چند درصد مصرف (مثلاً ۸۰,۹۵)",
    default="80,95",
    type_=str,
    validator=_percent_list,
    description="Percent of traffic used at which the customer is warned, comma separated.",
)

def _text_map(raw: Any) -> str | None:
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in raw.items()):
        return "every key and value must be text"
    return None


#: The main bot's own wording for the screens a reseller may also rewrite,
#: by constant name. Edited from the bot's admin menu; empty follows the
#: built-in copy, so improving a message improves it wherever it was left alone.
TEXT_OVERRIDES = SettingDefinition[dict[str, Any]](
    key="texts.overrides",
    label_fa="متن‌های سفارشی ربات",
    default={},
    type_=dict,
    validator=_text_map,
    description="Screen texts rewritten for the main bot, by constant name.",
)
RULES_ENABLED = SettingDefinition[bool](
    key="texts.rules_enabled",
    label_fa="نمایش بخش قوانین",
    default=False,
    type_=bool,
    description="Show a rules button on the home screen and answer /rules.",
)

DAILY_PURCHASE_LIMIT = SettingDefinition[int](
    key="purchase.daily_limit",
    label_fa="سقف تعداد خرید روزانهٔ هر کاربر",
    default=0,
    type_=int,
    minimum=0,
    description=(
        "New services one customer may buy per Tehran day. Renewals do not count."
        " 0 means no limit."
    ),
)

#: The referral programme. The pricing engine has always read these keys, and
#: nothing declared them, so the admin panel could not show or change them:
#: the 10% first-purchase share could only be edited in the database.
REFERRAL_ENABLED = SettingDefinition[bool](
    key=KEY_REFERRAL_ENABLED,
    label_fa="برنامهٔ زیرمجموعه‌گیری",
    default=True,
    type_=bool,
    description="Pay referrers when the people they invite buy.",
)
REFERRAL_FIRST_BPS = SettingDefinition[int](
    key=KEY_REFERRAL_FIRST_BPS,
    label_fa="سهم معرف از اولین خرید (درصد)",
    default=1_000,
    type_=int,
    minimum=0,
    maximum=10_000,
    render_as="bps",
    description="Share of the invitee's first order, in basis points.",
)
REFERRAL_FIRST_FIXED = SettingDefinition[int](
    key=KEY_REFERRAL_FIRST_FIXED,
    label_fa="پاداش ثابت معرف از اولین خرید (تومان)",
    default=0,
    type_=int,
    minimum=0,
    render_as="toman",
    description="A fixed amount per invitee's first order, on top of the share.",
)
REFERRAL_RECURRING_BPS = SettingDefinition[int](
    key=KEY_REFERRAL_RECURRING_BPS,
    label_fa="سهم معرف از خریدهای بعدی (درصد)",
    default=0,
    type_=int,
    minimum=0,
    maximum=10_000,
    render_as="bps",
    description="Share of every later order, in basis points.",
)
REFERRAL_RECURRING_FIXED = SettingDefinition[int](
    key=KEY_REFERRAL_RECURRING_FIXED,
    label_fa="پاداش ثابت معرف از خریدهای بعدی (تومان)",
    default=0,
    type_=int,
    minimum=0,
    render_as="toman",
    description="A fixed amount per later order.",
)
REFERRAL_INVITEE_BONUS = SettingDefinition[int](
    key=KEY_REFERRAL_INVITEE_BONUS,
    label_fa="هدیهٔ کاربری که با لینک دعوت آمده (تومان)",
    default=0,
    type_=int,
    minimum=0,
    render_as="toman",
    description="Credit for the invited customer.",
)

CARD_FOR_NEW_CUSTOMERS = SettingDefinition[bool](
    key="payments.card_for_new_customers",
    label_fa="کارت‌به‌کارت برای کاربری که هنوز خرید نکرده",
    default=True,
    type_=bool,
    description=(
        "Offer card-to-card to customers with no completed purchase. Off keeps"
        " first-time buyers on automatic methods, where fake receipts cannot land."
    ),
)

#: Matches `HIDEABLE` in the bot's menu module; the settings layer cannot import
#: presentation, so the names are repeated and a test holds the two together.
HIDEABLE_BUTTONS: frozenset[str] = frozenset(
    {"wallet", "reseller", "status", "referral", "faq", "support", "trial"}
)


def _button_list(raw: Any) -> str | None:
    names = {part.strip() for part in str(raw).split(",") if part.strip()}
    unknown = names - HIDEABLE_BUTTONS
    return f"unknown buttons: {', '.join(sorted(unknown))}" if unknown else None


def parse_hidden(raw: str) -> frozenset[str]:
    return frozenset(part.strip() for part in raw.split(",") if part.strip()) & HIDEABLE_BUTTONS


HIDDEN_BUTTONS = SettingDefinition[str](
    key="menu.hidden_buttons",
    label_fa="دکمه‌های خاموش صفحهٔ اصلی",
    default="",
    type_=str,
    validator=_button_list,
    description="Home-screen buttons switched off, comma separated. Edited from the bot.",
)

REFUND_WINDOW_HOURS = SettingDefinition[int](
    key="services.refund_window_hours",
    label_fa="مهلت برگشت وجه سرویس استفاده‌نشده (ساعت)",
    default=0,
    type_=int,
    minimum=0,
    maximum=720,
    description=(
        "Hours after purchase a customer may return a service that has used no"
        " traffic, for its price back into their wallet. 0 turns it off."
    ),
)

KICK_ON_SUSPEND = SettingDefinition[bool](
    key="channels.kick_on_suspend",
    label_fa="حذف کاربر مسدودشده از کانال‌های اجباری",
    default=False,
    type_=bool,
    description=(
        "When a customer is suspended, remove them from the shop's required channels"
        " too. The bot must be an administrator there."
    ),
)
CHANNEL_LEAVE_MESSAGE_FA = SettingDefinition[str](
    key="channels.leave_message_fa",
    label_fa="پیام به کاربری که از کانال اجباری خارج شد",
    default="",
    type_=str,
    description="Sent to a customer who leaves a required channel. Empty sends nothing.",
)

#: Devices a connection tutorial can be written for, in the order they are
#: offered. The bot shows only the ones the operator has filled in.
TUTORIAL_DEVICES: tuple[str, ...] = ("android", "ios", "windows", "mac", "linux")


def _tutorials(raw: Any) -> str | None:
    for device, entry in raw.items():
        if device not in TUTORIAL_DEVICES or not isinstance(entry, dict):
            return f"unknown device {device!r}"
        if entry.get("kind") not in {"text", "photo", "video"}:
            return f"{device}: kind must be text, photo or video"
    return None


TUTORIALS = SettingDefinition[dict[str, Any]](
    key="texts.tutorials",
    label_fa="آموزش اتصال به تفکیک دستگاه",
    default={},
    type_=dict,
    validator=_tutorials,
    description="Per-device connection tutorials (text, photo or video). Edited from the bot.",
)

DELETE_EXPIRED_AFTER_HOURS = SettingDefinition[int](
    key="services.delete_expired_after_hours",
    label_fa="حذف خودکار سرویس منقضی بعد از (ساعت)",
    default=0,
    type_=int,
    minimum=0,
    description=(
        "Delete the panel account of a service this many hours after it expired or ran"
        " out of traffic. 0 keeps them forever."
    ),
)

TRANSFER_ENABLED_WALLET = SettingDefinition[bool](
    key="wallet.transfer_enabled",
    label_fa="انتقال موجودی بین کاربران",
    default=False,
    type_=bool,
    description="Let a customer send wallet balance to another customer of the same shop.",
)
TRANSFER_MIN_TOMAN = SettingDefinition[int](
    key="wallet.transfer_min_toman",
    label_fa="حداقل مبلغ انتقال موجودی (تومان)",
    default=10_000,
    type_=int,
    minimum=1,
    maximum=100_000_000,
    description="The smallest wallet transfer a customer may make, in Toman.",
)

NEWCOMER_GIFT_AFTER_HOURS = SettingDefinition[int](
    key="gifts.newcomer_after_hours",
    label_fa="هدیه به عضو جدیدی که خرید نکرده، بعد از (ساعت)",
    default=0,
    type_=int,
    minimum=0,
    maximum=24 * 30,
    description=(
        "Credit a customer who joined this many hours ago and has bought nothing yet."
        " Once per customer, the platform's shop only. 0 switches it off."
    ),
)
NEWCOMER_GIFT_TOMAN = SettingDefinition[int](
    key="gifts.newcomer_amount_toman",
    label_fa="مبلغ هدیهٔ عضو جدید (تومان)",
    default=0,
    type_=int,
    minimum=0,
    maximum=10_000_000,
    description="How much that customer's wallet is credited, in Toman. 0 switches it off.",
)
NEWCOMER_GIFT_MESSAGE_FA = SettingDefinition[str](
    key="gifts.newcomer_message_fa",
    label_fa="پیام هدیهٔ عضو جدید",
    default="هنوز سرویسی نگرفتی؟ یه هدیه به کیف پولت اضافه کردیم تا با تخفیف شروع کنی 🎁",
    type_=str,
    description="Sent with the gift. Empty sends only the wallet notice.",
)

SHOW_CAPACITY = SettingDefinition[bool](
    key="shop.show_capacity",
    label_fa="نمایش ظرفیت باقی‌ماندهٔ سرور هنگام خرید",
    default=False,
    type_=bool,
    description="Show how many accounts a product's server still has room for.",
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
        ALERTS_SERVICES_CHAT,
        ALERTS_TRIALS_CHAT,
        RENAME_ENABLED,
        TRANSFER_ENABLED,
        BACKUP_CHAT,
        BACKUP_INTERVAL_HOURS,
        TOPUP_MIN_TOMAN,
        TOPUP_MAX_TOMAN,
        REMINDER_EXPIRY_DAYS,
        REMINDER_TRAFFIC_PERCENTS,
        TEXT_OVERRIDES,
        RULES_ENABLED,
        DAILY_PURCHASE_LIMIT,
        REFERRAL_ENABLED,
        REFERRAL_FIRST_BPS,
        REFERRAL_FIRST_FIXED,
        REFERRAL_RECURRING_BPS,
        REFERRAL_RECURRING_FIXED,
        REFERRAL_INVITEE_BONUS,
        CARD_FOR_NEW_CUSTOMERS,
        HIDDEN_BUTTONS,
        REFUND_WINDOW_HOURS,
        KICK_ON_SUSPEND,
        CHANNEL_LEAVE_MESSAGE_FA,
        TUTORIALS,
        DELETE_EXPIRED_AFTER_HOURS,
        SHOW_CAPACITY,
        NEWCOMER_GIFT_AFTER_HOURS,
        NEWCOMER_GIFT_TOMAN,
        NEWCOMER_GIFT_MESSAGE_FA,
        TRANSFER_ENABLED_WALLET,
        TRANSFER_MIN_TOMAN,
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

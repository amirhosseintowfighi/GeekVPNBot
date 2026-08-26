"""Persian rendering: the copy layer."""

from __future__ import annotations

import pytest

from geekvpn.domain.notifications.enums import NotificationCategory
from geekvpn.domain.notifications.errors import (
    MissingTemplateField,
    TemplateNotFound,
)
from geekvpn.domain.notifications.message import (
    CATALOG,
    PERSIAN_DIGITS,
    THOUSANDS_SEP,
    RenderedMessage,
    fa_digits,
    fa_gib,
    fa_number,
    fa_toman,
    render,
    template_keys,
)

LATIN = set("abcdefghijklmnopqrstuvwxyz")

#: Client apps a customer is told to install. Proper nouns, and the only Latin
#: a reader is meant to see - a store search for "وی‌تو‌ری" finds nothing.
APP_NAMES = ("v2rayNG", "Streisand", "v2box")


def test_digits_become_persian():
    assert fa_digits(2026) == "\u06f2\u06f0\u06f2\u06f6"


def test_numbers_are_grouped_with_the_persian_separator():
    grouped = fa_number(680000)
    assert THOUSANDS_SEP in grouped
    assert not any(ch.isdigit() and ch not in PERSIAN_DIGITS for ch in grouped)


def test_toman_carries_its_unit():
    assert fa_toman(50000).endswith("\u062a\u0648\u0645\u0627\u0646")


def test_unmetered_volume_reads_as_unlimited_not_zero():
    assert fa_gib(None) == "\u0646\u0627\u0645\u062d\u062f\u0648\u062f"


def test_fractional_volume_uses_the_persian_decimal_separator():
    text = fa_gib(12.5)
    assert "\u066b" in text
    assert "." not in text


def test_integral_volume_has_no_decimal_part():
    assert "\u066b" not in fa_gib(100.0)


def test_rendering_substitutes_and_persianises_numbers():
    message = render("expiry.soon", plan="Geek Turbo", days=3)
    assert "\u06f3" in message.body_fa
    assert "Geek Turbo" in message.body_fa


def test_rendering_an_unknown_key_fails_loudly():
    with pytest.raises(TemplateNotFound):
        render("no.such.template")


def test_missing_field_is_rejected_rather_than_left_blank():
    """A blank Telegram push is worse than a missing one."""
    with pytest.raises(MissingTemplateField):
        render("expiry.soon", plan="Geek Turbo")


def test_booleans_are_not_rendered_as_persian_one():
    message = render("broadcast.custom", title="x", body=True)
    assert "\u06f1" not in message.body_fa


def test_every_template_carries_a_category():
    for key, template in CATALOG.items():
        assert isinstance(template.category, NotificationCategory), key


def test_every_template_body_is_persian():
    """The whole point of a central catalogue: one place to audit.

    Placeholder names are Latin by necessity, and so are HTML tags - `<code>`
    around a subscription link is what makes it tap-to-copy in Telegram, and
    the reader never sees it. Both are stripped: what is being checked is that
    no English *word* reaches a Persian speaker, not that the string contains
    no Latin bytes.

    App names are the third exception, and the only one a reader does see. A
    customer holding a subscription link has to type "v2rayNG" into a store
    search box to get anywhere; transliterating it into Persian would leave
    them with a name that finds nothing. The list is explicit so that adding
    an English *sentence* still fails here.
    """
    import re

    for key, template in CATALOG.items():
        for text in (template.title_fa, template.body_fa):
            stripped = re.sub(r"\{[a-z_]+\}", "", text)
            stripped = re.sub(r"</?[a-z]+>", "", stripped)
            for app in APP_NAMES:
                stripped = stripped.replace(app, "")
            assert not (set(stripped.lower()) & LATIN), f"{key}: {stripped}"


def test_transactional_templates_are_critical():
    """Money and dead services must not be mutable."""
    for key in (
        "payment.approved",
        "payment.rejected",
        "payment.refunded",
        "wallet.credited",
        "wallet.debited",
        "purchase.completed",
        "expiry.expired",
        "traffic.exhausted",
        "ticket.replied",
    ):
        assert CATALOG[key].category is NotificationCategory.CRITICAL, key


def test_marketing_templates_are_mutable():
    assert CATALOG["campaign.launched"].category is NotificationCategory.PROMOS
    assert CATALOG["referral.reward"].category is NotificationCategory.PROMOS
    assert CATALOG["broadcast.custom"].category is NotificationCategory.NEWS


def test_preview_truncates_with_an_ellipsis():
    message = RenderedMessage(
        key="k",
        category=NotificationCategory.NEWS,
        title_fa="t",
        body_fa="\u0627" * 400,
    )
    preview = message.preview(limit=50)
    assert len(preview) == 50
    assert preview.endswith("\u2026")


def test_short_body_is_previewed_unchanged():
    message = RenderedMessage(
        key="k",
        category=NotificationCategory.NEWS,
        title_fa="t",
        body_fa="\u0633\u0644\u0627\u0645",
    )
    assert message.preview() == "\u0633\u0644\u0627\u0645"


def test_telegram_text_bolds_the_title():
    message = render("expiry.today", plan="Geek Elite")
    assert message.telegram_text().startswith("<b>")


def test_inbox_payload_is_serialisable_and_persian():
    payload = render("expiry.today", plan="Geek Elite").inbox_payload()
    assert set(payload) == {
        "key",
        "category",
        "title_fa",
        "body_fa",
        "preview_fa",
        "action",
    }


def test_catalogue_keys_are_sorted_and_unique():
    keys = template_keys()
    assert list(keys) == sorted(set(keys))


def test_the_delivery_message_says_what_to_do_with_the_link():
    """The one message a paying customer has to act on.

    It used to hand over a link and one sentence. A first-time buyer who has
    never seen a subscription URL pastes it into a browser, gets a page of
    JSON, and opens a ticket - so the steps are spelled out, app names and all,
    on the message that arrives at the moment they are looking.
    """
    body = render("purchase.delivered", link="https://sub.example/x").body_fa

    assert "https://sub.example/x" in body
    assert "<code>" in body
    assert any(app in body for app in APP_NAMES)


def test_both_delivery_messages_celebrate():
    """Somebody just paid. The two variants differ only in whether the link
    was ready, which is our problem and not something to be glum at the
    customer about."""
    with_link = render("purchase.delivered", link="x")
    without = render("purchase.delivered_no_link")

    assert with_link.title_fa == without.title_fa
    assert "🎉" in with_link.title_fa

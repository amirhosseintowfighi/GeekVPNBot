"""Output escaping for Telegram HTML and rendered links."""

from __future__ import annotations

from geekvpn.infrastructure.security.escaping import (
    escape_html,
    escape_html_attribute,
    safe_url,
    truncate_for_display,
)


class TestTelegramHtml:
    def test_markup_in_customer_text_is_neutralised(self):
        assert escape_html("<b>bold</b>") == "&lt;b&gt;bold&lt;/b&gt;"

    def test_an_unclosed_tag_cannot_break_our_own_message(self):
        """Telegram rejects malformed HTML, so this is an availability bug.

        A customer whose ticket subject is "<b" could otherwise make every
        notification about that ticket undeliverable.
        """
        assert "<" not in escape_html("مشکل دارم <b")

    def test_ampersands_are_escaped_once_not_twice(self):
        """Replacing < before & yields &amp;lt; and renders literally."""
        assert escape_html("a & b") == "a &amp; b"
        assert escape_html("<") == "&lt;"
        assert "&amp;lt;" not in escape_html("<")

    def test_persian_text_survives_untouched(self):
        text = "اشتراک من تمام شده‌است"
        assert escape_html(text) == text

    def test_the_zero_width_non_joiner_is_preserved(self):
        """ZWNJ is required Persian orthography, not a control character."""
        assert "\u200c" in escape_html("می‌خواهم")

    def test_direction_overrides_are_removed(self):
        """An override can visually reverse an amount in an admin list."""
        assert "\u202e" not in escape_html("مبلغ \u202e50,000")

    def test_control_characters_are_removed(self):
        assert "\x00" not in escape_html("a\x00b")
        assert "\x1b" not in escape_html("a\x1b[31mred")

    def test_newlines_survive_in_body_text(self):
        """A ticket body legitimately has line breaks."""
        assert "\n" in escape_html("line one\nline two")

    def test_newlines_are_dropped_inside_an_attribute(self):
        assert "\n" not in escape_html_attribute("a\nb")

    def test_quotes_are_escaped_for_attributes(self):
        assert '"' not in escape_html_attribute('say "hi"')


class TestUrlSafety:
    def test_https_is_allowed(self):
        assert safe_url("https://geekvpn.example/x") == "https://geekvpn.example/x"

    def test_telegram_links_are_allowed(self):
        assert safe_url("tg://resolve?domain=GeekVpnBot")

    def test_javascript_is_refused(self):
        assert safe_url("javascript:alert(1)") is None

    def test_case_does_not_help_the_attacker(self):
        assert safe_url("JavaScript:alert(1)") is None

    def test_leading_control_characters_do_not_smuggle_a_scheme(self):
        """Browsers strip these before parsing, defeating a startswith check."""
        assert safe_url("\x01javascript:alert(1)") is None
        assert safe_url("  \tjavascript:alert(1)") is None

    def test_a_whole_document_in_a_data_url_is_refused(self):
        assert safe_url("data:text/html;base64,PHNjcmlwdD4=") is None

    def test_protocol_relative_urls_are_refused(self):
        assert safe_url("//evil.example/x") is None

    def test_a_relative_path_is_allowed(self):
        assert safe_url("/admin/payments") == "/admin/payments"

    def test_empty_input_yields_none(self):
        assert safe_url("") is None
        assert safe_url("   ") is None


class TestTruncation:
    def test_short_text_is_unchanged(self):
        assert truncate_for_display("سلام") == "سلام"

    def test_long_text_is_cut_with_an_ellipsis(self):
        result = truncate_for_display("ا" * 500, limit=50)
        assert len(result) == 50
        assert result.endswith("\u2026")

    def test_truncation_happens_before_escaping_so_entities_stay_whole(self):
        """Cutting an escaped string can leave "&am", which renders literally."""
        escaped = escape_html(truncate_for_display("&" * 40, limit=20))
        assert "&am" not in escaped.replace("&amp;", "")

    def test_control_characters_are_stripped_while_truncating(self):
        assert "\x00" not in truncate_for_display("a\x00b")

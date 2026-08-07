"""Tests for secret loading and weak-secret refusal."""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.secrets_provider import (
    MIN_KEY_LENGTH,
    ChainSecretsProvider,
    EnvSecretsProvider,
    SecretsError,
    StaticSecretsProvider,
    audit,
    generate_secret,
    optional,
    redact,
    require,
    require_key,
    weakness_of,
)

STRONG = "tG7-xQ2vB9pLmN4tR6yU8wZ3aC5eG1hJ0sDfK"


class TestFileConvention:
    def test_a_mounted_file_supplies_the_secret(self, tmp_path=None) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jwt_secret"
            path.write_text(STRONG, encoding="utf-8")
            provider = EnvSecretsProvider(environ={"JWT_SECRET_FILE": str(path)})
            assert provider.get("JWT_SECRET") == STRONG

    def test_the_trailing_newline_from_echo_is_stripped(self) -> None:
        # `echo secret > file` appends a newline. Not stripping it is the cause
        # of a whole genre of "the password is wrong but it looks right" bugs.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text(f"{STRONG}\n", encoding="utf-8")
            provider = EnvSecretsProvider(environ={"S_FILE": str(path)})
            assert provider.get("S") == STRONG

    def test_the_file_wins_over_the_environment_variable(self) -> None:
        # A mounted secret is a deliberate act; a stray environment variable is
        # usually inherited from a shell or a compose default.
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("from-the-file-" + STRONG, encoding="utf-8")
            provider = EnvSecretsProvider(
                environ={"S": "from-the-environment", "S_FILE": str(path)}
            )
            assert provider.get("S") == "from-the-file-" + STRONG

    def test_an_empty_file_is_an_error_not_an_empty_secret(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "secret"
            path.write_text("   \n", encoding="utf-8")
            provider = EnvSecretsProvider(environ={"S_FILE": str(path)})
            with pytest.raises(SecretsError):
                provider.get("S")

    def test_a_missing_file_names_the_path_but_never_a_value(self) -> None:
        provider = EnvSecretsProvider(environ={"S_FILE": "/nonexistent/secret"})
        with pytest.raises(SecretsError) as error:
            provider.get("S")
        assert "/nonexistent/secret" in str(error.value)

    def test_an_unset_secret_reads_as_none_rather_than_an_empty_string(self) -> None:
        assert EnvSecretsProvider(environ={"S": ""}).get("S") is None


class TestRefusals:
    def test_a_missing_secret_tells_the_operator_both_ways_to_set_it(self) -> None:
        with pytest.raises(SecretsError) as error:
            require(StaticSecretsProvider({}), "JWT_SECRET")
        message = str(error.value)
        assert "JWT_SECRET" in message and "JWT_SECRET_FILE" in message

    def test_well_known_placeholders_are_refused(self) -> None:
        for weak in ("password", "changeme", "geekvpn", "postgres", "admin"):
            with pytest.raises(SecretsError):
                require(StaticSecretsProvider({"P": weak}), "P")

    def test_the_projects_own_development_secret_is_refused(self) -> None:
        development = "insecure-development-key-do-not-use-in-production"
        assert weakness_of(development) is not None
        with pytest.raises(SecretsError):
            require_key(StaticSecretsProvider({"K": development}), "K")

    def test_a_long_but_repetitive_key_is_refused(self) -> None:
        # "abababab..." passes a length check and fails a real one.
        assert weakness_of("ab" * 20, min_length=MIN_KEY_LENGTH) is not None
        assert weakness_of("x" * 64, min_length=MIN_KEY_LENGTH) is not None

    def test_a_short_key_is_refused_even_when_random(self) -> None:
        with pytest.raises(SecretsError):
            require_key(StaticSecretsProvider({"K": "aB3-xQ9"}), "K")

    def test_a_strong_key_passes(self) -> None:
        assert require_key(StaticSecretsProvider({"K": STRONG}), "K") == STRONG

    def test_the_refusal_reason_never_contains_the_secret(self) -> None:
        # The reason gets logged; the secret must not.
        secret = "insecure-" + STRONG
        with pytest.raises(SecretsError) as error:
            require_key(StaticSecretsProvider({"K": secret}), "K")
        assert secret not in str(error.value)


class TestOptionalAndChain:
    def test_an_unset_optional_secret_is_none(self) -> None:
        assert optional(StaticSecretsProvider({}), "MAYBE") is None

    def test_an_optional_secret_that_is_set_to_junk_still_fails(self) -> None:
        # Being optional means "may be absent", not "may be weak".
        with pytest.raises(SecretsError):
            optional(StaticSecretsProvider({"MAYBE": "changeme"}), "MAYBE")

    def test_the_first_provider_holding_the_secret_wins(self) -> None:
        chain = ChainSecretsProvider(
            [
                StaticSecretsProvider({}),
                StaticSecretsProvider({"S": "first"}),
                StaticSecretsProvider({"S": "second"}),
            ]
        )
        assert chain.get("S") == "first"

    def test_a_chain_with_nothing_returns_none(self) -> None:
        assert ChainSecretsProvider([StaticSecretsProvider({})]).get("S") is None


class TestAudit:
    def test_every_problem_is_reported_at_once(self) -> None:
        # An operator's first deploy should produce one list, not five
        # consecutive failed boots.
        provider = StaticSecretsProvider({"WEAK": "password", "SHORT_KEY": "abc", "GOOD": STRONG})
        problems = audit(provider, ["WEAK", "MISSING", "GOOD"], keys=["SHORT_KEY"])

        joined = " | ".join(problems)
        assert len(problems) == 3
        assert "WEAK" in joined and "MISSING" in joined and "SHORT_KEY" in joined
        assert "GOOD" not in joined

    def test_a_clean_configuration_reports_nothing(self) -> None:
        provider = StaticSecretsProvider({"A": STRONG, "B": STRONG})
        assert audit(provider, ["A"], keys=["B"]) == []


class TestGenerationAndRedaction:
    def test_generated_secrets_are_long_distinct_and_url_safe(self) -> None:
        generated = {generate_secret() for _ in range(200)}
        assert len(generated) == 200
        for value in generated:
            assert len(value) == 48
            assert weakness_of(value, min_length=MIN_KEY_LENGTH) is None

    def test_a_generated_secret_never_trips_the_weakness_check(self) -> None:
        """The generator and the validator must agree.

        `weakness_of` rejects any value containing a development marker, and a
        random 48-character string spells "todo" roughly once every 23,000
        draws. Before the generator re-drew, it would occasionally hand an
        operator a secret that this module's own guardrail then refused at
        boot - and the failure surfaced as an intermittent test, which is the
        least useful place to notice it.
        """
        for _ in range(5_000):
            assert weakness_of(generate_secret(), min_length=MIN_KEY_LENGTH) is None

    def test_generating_a_weak_length_is_refused(self) -> None:
        with pytest.raises(ValueError):
            generate_secret(16)

    def test_redaction_keeps_only_the_ends(self) -> None:
        assert redact("sk_live_abcdefghijklmnop") == "sk_l...mnop"

    def test_redaction_of_a_short_value_shows_nothing(self) -> None:
        assert redact("abc") == "***"

    def test_redaction_of_nothing_says_unset(self) -> None:
        assert redact(None) == "<unset>"

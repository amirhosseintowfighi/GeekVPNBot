"""Tests for application-layer encryption.

These are adversarial on purpose: a round-trip test proves almost nothing about
an encryption module. What matters is that it refuses the attacks the design
claims to stop.
"""

from __future__ import annotations

import pytest

from geekvpn.infrastructure.security.crypto import (
    DecryptionError,
    EncryptionConfigError,
    KeyRing,
    UnknownKeyError,
    constant_time_equals,
    digits_only,
    is_ciphertext,
    mask_card,
)

MASTER = "kQ7_x2vB9pLmN4tR6yU8wZ3aC5eG1hJ0sD-fK"  # 37 chars, test-only
OTHER_MASTER = "Zx4-Wq8_Nm2Bv6Ct0Ly9Rs3Ju7Hg5Fd1Pa-Ke"
CONTEXT = "panel:credentials:9f2c"


def ring(*, active: str = "k1", retired: tuple[str, ...] = ()) -> KeyRing:
    return KeyRing.from_master_secret(MASTER, active_key_id=active, retired_key_ids=retired)


def test_a_secret_survives_a_round_trip_unchanged() -> None:
    keys = ring()
    secret = "p@ssw0rd با حروف فارسی و 🔐"
    token = keys.encrypt(secret, context=CONTEXT)

    assert token != secret
    assert secret not in token
    assert keys.decrypt(token, context=CONTEXT) == secret


def test_the_same_plaintext_never_produces_the_same_ciphertext() -> None:
    # A repeated nonce in GCM leaks the authentication key. If this ever fails,
    # the module is catastrophically broken, not merely inelegant.
    keys = ring()
    tokens = {keys.encrypt("same-password", context=CONTEXT) for _ in range(50)}
    assert len(tokens) == 50


def test_a_ciphertext_cannot_be_moved_to_another_row() -> None:
    # The attack: an attacker with write access copies the encrypted password of
    # a panel they control over a production panel's column.
    keys = ring()
    token = keys.encrypt("prod-panel-password", context="panel:credentials:PROD")

    with pytest.raises(DecryptionError):
        keys.decrypt(token, context="panel:credentials:ATTACKER")


def test_tampering_with_a_single_character_is_detected() -> None:
    keys = ring()
    token = keys.encrypt("do-not-modify", context=CONTEXT)
    scheme, key_id, payload = token.split(".")
    flipped = "A" if payload[0] != "A" else "B"
    tampered = f"{scheme}.{key_id}.{flipped}{payload[1:]}"

    with pytest.raises(DecryptionError):
        keys.decrypt(tampered, context=CONTEXT)


def test_another_deployments_key_cannot_read_our_data() -> None:
    ours = ring()
    theirs = KeyRing.from_master_secret(OTHER_MASTER)
    token = ours.encrypt("our-secret", context=CONTEXT)

    with pytest.raises(DecryptionError):
        theirs.decrypt(token, context=CONTEXT)


def test_the_error_message_never_explains_why_decryption_failed() -> None:
    # A decryption oracle that distinguishes "wrong key" from "wrong context"
    # from "tampered" is a decryption oracle.
    keys = ring()
    token = keys.encrypt("secret", context=CONTEXT)
    with pytest.raises(DecryptionError) as wrong_context:
        keys.decrypt(token, context="other")
    scheme, key_id, payload = token.split(".")
    with pytest.raises(DecryptionError) as tampered:
        keys.decrypt(
            f"{scheme}.{key_id}.{'A' if payload[0] != 'A' else 'B'}{payload[1:]}", context=CONTEXT
        )

    assert str(wrong_context.value) == str(tampered.value)


class TestRotation:
    def test_a_retired_key_still_reads_its_own_rows(self) -> None:
        old = ring(active="k1")
        token = old.encrypt("written-last-year", context=CONTEXT)

        rotated = ring(active="k2", retired=("k1",))
        assert rotated.decrypt(token, context=CONTEXT) == "written-last-year"

    def test_old_rows_are_identifiable_so_a_backfill_can_find_them(self) -> None:
        rotated = ring(active="k2", retired=("k1",))
        old_token = ring(active="k1").encrypt("old", context=CONTEXT)
        new_token = rotated.encrypt("new", context=CONTEXT)

        assert rotated.needs_rotation(old_token) is True
        assert rotated.needs_rotation(new_token) is False

    def test_rewrapping_preserves_the_plaintext_and_clears_the_flag(self) -> None:
        rotated = ring(active="k2", retired=("k1",))
        old_token = ring(active="k1").encrypt("unchanged", context=CONTEXT)

        fresh = rotated.rewrap(old_token, context=CONTEXT)

        assert rotated.decrypt(fresh, context=CONTEXT) == "unchanged"
        assert rotated.needs_rotation(fresh) is False

    def test_dropping_a_key_that_still_has_rows_fails_loudly(self) -> None:
        # The recoverable failure: put the key back. This is why the key id
        # travels inside the ciphertext.
        token = ring(active="k1").encrypt("orphan", context=CONTEXT)
        without_k1 = ring(active="k2")

        with pytest.raises(UnknownKeyError):
            without_k1.decrypt(token, context=CONTEXT)


class TestBlindIndex:
    def test_the_same_value_always_indexes_the_same_way(self) -> None:
        keys = ring()
        assert keys.blind_index("6037991234567890", context="card") == keys.blind_index(
            "6037991234567890", context="card"
        )

    def test_the_index_survives_key_rotation(self) -> None:
        # Deliberate: the blind index key is derived from the master secret, not
        # from the data key. Rotating the data key must not silently destroy
        # every lookup index in the database.
        before = ring(active="k1").blind_index("6037991234567890", context="card")
        after = ring(active="k2", retired=("k1",)).blind_index("6037991234567890", context="card")
        assert before == after

    def test_different_contexts_produce_different_indexes(self) -> None:
        keys = ring()
        assert keys.blind_index("1234", context="card") != keys.blind_index("1234", context="txid")

    def test_another_deployment_cannot_reproduce_our_index(self) -> None:
        # Why a keyed HMAC and not a bare SHA-256: a card number has too little
        # entropy to survive an offline digest attack.
        value = "6037991234567890"
        assert ring().blind_index(value, context="card") != KeyRing.from_master_secret(
            OTHER_MASTER
        ).blind_index(value, context="card")


class TestConfigurationRefusals:
    def test_a_short_master_secret_is_refused(self) -> None:
        with pytest.raises(EncryptionConfigError):
            KeyRing.from_master_secret("too-short")

    def test_an_empty_context_is_refused(self) -> None:
        with pytest.raises(EncryptionConfigError):
            ring().encrypt("x", context="")

    def test_a_key_id_containing_a_dot_is_refused(self) -> None:
        # It would make the token ambiguous to parse.
        with pytest.raises(EncryptionConfigError):
            KeyRing.from_master_secret(MASTER, active_key_id="k.1")

    def test_key_material_never_appears_in_a_repr(self) -> None:
        from geekvpn.infrastructure.security.crypto import DataKey, derive_key

        key = DataKey(key_id="k1", material=derive_key(MASTER, key_id="k1"))
        assert "redacted" in repr(key)
        assert key.material.hex() not in repr(key)


class TestBackfillSupport:
    def test_encrypted_values_are_recognisable(self) -> None:
        assert is_ciphertext(ring().encrypt("x", context=CONTEXT)) is True

    def test_plaintext_and_empty_values_are_not_mistaken_for_ciphertext(self) -> None:
        # A backfill migration must be safe to re-run without double-encrypting.
        assert is_ciphertext("plain-password") is False
        assert is_ciphertext("") is False
        assert is_ciphertext(None) is False
        assert is_ciphertext("v1.k1") is False

    def test_garbage_is_refused_rather_than_crashing_on_base64(self) -> None:
        with pytest.raises(DecryptionError):
            ring().decrypt("v1.k1.!!!not-base64!!!", context=CONTEXT)

    def test_a_truncated_token_is_refused(self) -> None:
        with pytest.raises(DecryptionError):
            ring().decrypt("v1.k1.AAAA", context=CONTEXT)


class TestOperatorSafeHelpers:
    def test_persian_digits_fold_to_ascii(self) -> None:
        # A customer pasting from a Persian banking app must hit the same index
        # entry as one typing on a Latin keyboard.
        assert digits_only("۶۰۳۷-۹۹۱۲-۳۴۵۶-۷۸۹۰") == "6037991234567890"

    def test_arabic_indic_digits_fold_too(self) -> None:
        assert digits_only("٦٠٣٧") == "6037"

    def test_a_masked_card_keeps_only_the_bin_and_the_last_four(self) -> None:
        # PCI allows the six-digit BIN and the last four. Not a digit more.
        assert mask_card("6037991234567890") == "603799" + "*" * 6 + "7890"

    def test_masking_never_leaks_the_middle_digits(self) -> None:
        masked = mask_card("6037991234567890")
        assert "991234" not in masked
        assert masked.count("*") == 6

    def test_a_short_string_is_fully_masked_rather_than_partly_shown(self) -> None:
        assert mask_card("12345") == "*****"

    def test_secret_comparison_is_constant_time_and_correct(self) -> None:
        assert constant_time_equals("abc", "abc") is True
        assert constant_time_equals("abc", "abd") is False
        assert constant_time_equals("abc", "abcd") is False

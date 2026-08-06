"""Receipt and transaction-hash evidence.

The fingerprint is the point. The commonest fraud in card-to-card sales is
forwarding one genuine receipt against several orders, and a reviewer looking
at a photo cannot tell they have seen it before.
"""

from __future__ import annotations

from geekvpn.domain.payments.enums import PaymentMethod
from geekvpn.domain.payments.errors import PaymentValidationError
from geekvpn.domain.payments.proof import (
    MAX_TXID_LENGTH,
    MIN_TXID_LENGTH,
    PaymentProof,
    fingerprint,
    normalise_reference,
)
from tests.unit.payments.fakes import EPOCH

TXID = "0x9f2b7c41ae8d5063fb1e2a7c9048d31b"


def test_card_proof_fingerprints_the_bytes_not_the_file_id():
    # A forwarded photo gets a fresh Telegram file id but identical bytes, so
    # the digest must come from the content.
    first = PaymentProof.for_card(
        file_id="AgACAgQ-first", image_digest="deadbeef", submitted_at=EPOCH
    )
    forwarded = PaymentProof.for_card(
        file_id="AgACAgQ-second", image_digest="deadbeef", submitted_at=EPOCH
    )
    assert first.reference != forwarded.reference
    assert first.digest == forwarded.digest
    assert first.method is PaymentMethod.CARD


def test_card_proof_needs_a_file_and_a_digest():
    for kwargs in (
        {"file_id": "   ", "image_digest": "deadbeef"},
        {"file_id": "file-1", "image_digest": "  "},
    ):
        try:
            PaymentProof.for_card(submitted_at=EPOCH, **kwargs)
        except PaymentValidationError:
            pass
        else:
            raise AssertionError(f"unfingerprintable proof accepted: {kwargs}")


def test_crypto_proof_normalises_the_hash_before_fingerprinting():
    # Customers paste hashes with stray spaces and mixed case. The same
    # transaction must produce the same digest however it was typed.
    clean = PaymentProof.for_crypto(txid=TXID, network="TRC20", submitted_at=EPOCH)
    messy = PaymentProof.for_crypto(txid=f"  {TXID.upper()} ", network="trc20", submitted_at=EPOCH)
    assert clean.digest == messy.digest
    assert clean.reference == messy.reference
    assert clean.network == "trc20"


def test_a_hash_that_is_too_short_is_rejected_before_a_human_sees_it():
    try:
        PaymentProof.for_crypto(txid="abc", network="trc20", submitted_at=EPOCH)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a nonsense transaction hash reached the queue")


def test_hash_bounds_are_consistent_with_the_bot_validation():
    assert MIN_TXID_LENGTH == 10
    assert MAX_TXID_LENGTH >= 64
    try:
        PaymentProof.for_crypto(
            txid="a" * (MAX_TXID_LENGTH + 1), network="trc20", submitted_at=EPOCH
        )
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("an absurdly long hash was accepted")


def test_a_hash_with_impossible_characters_is_rejected():
    try:
        PaymentProof.for_crypto(txid="abcd efgh ijkl!!", network="trc20", submitted_at=EPOCH)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a malformed hash was accepted")


def test_crypto_proof_requires_a_network():
    try:
        PaymentProof.for_crypto(txid=TXID, network="  ", submitted_at=EPOCH)
    except PaymentValidationError:
        pass
    else:
        raise AssertionError("a chainless crypto payment was accepted")


def test_normalise_and_fingerprint_are_stable():
    assert normalise_reference("  AbC-123  ") == normalise_reference("abc-123")
    assert fingerprint("abc-123") == fingerprint("abc-123")
    assert fingerprint("abc-123") != fingerprint("abc-124")

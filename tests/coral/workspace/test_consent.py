"""PushConsent digests are stable and order-independent in JSON keys."""

from __future__ import annotations

from coral.workspace.consent import PushConsent, consent_digest


def test_consent_digest_is_hex_sha256_of_canonical_grant() -> None:
    consent = PushConsent(
        run_id="run-1",
        remote="origin",
        ref_prefix="refs/heads/coral/r-0123456789ab/",
        granted_by="alice",
        granted_at=1_700_000_000,
    )
    digest = consent_digest(consent)
    assert len(digest) == 64
    assert digest == consent_digest(consent)
    other = PushConsent(
        run_id="run-1",
        remote="origin",
        ref_prefix="refs/heads/coral/r-0123456789ab/",
        granted_by="bob",
        granted_at=1_700_000_000,
    )
    assert consent_digest(other) != digest

"""Per-run push consent for host-channel ``push`` (WSP-07 / OQ-39).

Consent is granted at run start and recorded as the additive K3 kind
``push.consented``. The host refuses any ``push`` whose ``consent_digest`` does
not match :func:`consent_digest` for that grant.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

# Digests are hex SHA-256 over a canonical JSON object of the grant fields.
_DIGEST_FIELDS = ("run_id", "remote", "ref_prefix", "granted_by", "granted_at")


@dataclass(frozen=True)
class PushConsent:
    """
    One run's permission to push under ``ref_prefix`` on ``remote``.

    :param run_id: The engine run id.
    :param remote: Remote name the start dialog named (e.g. ``origin``).
    :param ref_prefix: Allowed destination prefix, e.g. ``refs/heads/coral/r-<run12>/``.
    :param granted_by: Actor who confirmed start.
    :param granted_at: Unix epoch seconds when consent was granted.
    """

    run_id: str
    remote: str
    ref_prefix: str
    granted_by: str
    granted_at: int


def consent_digest(consent: PushConsent) -> str:
    """Hex SHA-256 of the canonical grant; the host compares this to ``consent_digest``."""
    payload = {
        "run_id": consent.run_id,
        "remote": consent.remote,
        "ref_prefix": consent.ref_prefix,
        "granted_by": consent.granted_by,
        "granted_at": consent.granted_at,
    }
    assert tuple(payload) == _DIGEST_FIELDS
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()


__all__ = ["PushConsent", "consent_digest"]

"""Gate integrity: whether a step of a run could answer its own gate, as far as the facts tell.

A gate is worth its answer only when no agent in the run can act as the run's owner. The
label is ``enforced`` only on a server that signs users in with accounts, whose config the
label verifies, that creates no claude-native steps, for a run whose own host reports an OS
sandbox at a policy revision the sandbox probe measured with nothing left open. Any fact
that is unknown or unverified reads ``not_enforced`` and names its reason.

Per sandbox and policy revision, the table holds two parts: the owners of the paths probe
15 pins open (kept equal to its pins by a test in ``tests/e2e/coral/test_sandbox_probe.py``)
and the declared blockers no probe measures. ``enforced`` needs both empty. The label reads
the server and the run now; it covers Coral's steps only, not other agents of the owner.
Pure: no I/O, standard library only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import astuple, dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Literal

GateIntegrityLabel = Literal["enforced", "not_enforced"]


class GateIntegrityReason(StrEnum):
    """
    Why a gate is not Enforced, in the order a label names them.
    ``server_mode_not_verified``: the server does not sign users in with accounts.
    ``server_config_not_verified``: a server setting could hand a step an owner
    credential, or was not read.
    ``native_steps_enabled``: the server may create claude-native steps.
    ``host_sandbox_unknown``: the run's host is offline, unreported, or on a sandbox no
    probe measured.
    ``host_sandbox_open``: the run's sandbox still has an open owner path.
    """

    SERVER_MODE_NOT_VERIFIED = "server_mode_not_verified"
    SERVER_CONFIG_NOT_VERIFIED = "server_config_not_verified"
    NATIVE_STEPS_ENABLED = "native_steps_enabled"
    HOST_SANDBOX_UNKNOWN = "host_sandbox_unknown"
    HOST_SANDBOX_OPEN = "host_sandbox_open"


REASONS: tuple[GateIntegrityReason, ...] = tuple(GateIntegrityReason)
VERIFIED_SERVER_MODES: frozenset[str] = frozenset({"accounts"})


@dataclass(frozen=True)
class HostSandboxPolicy:
    """
    A host's OS sandbox and the revision of Coral's step sandbox rules it runs.

    :param backend: ``"seatbelt"``, ``"bwrap"``, or another name the host reported.
    :param revision: The host's ``coral_sandbox_policy`` revision, e.g. ``"1"``.
    """

    backend: str
    revision: str


@dataclass(frozen=True)
class SandboxBlockers:
    """
    What keeps one sandbox policy from verifying a gate.

    :param probed: The owner tickets of the paths probe 15 pins open there.
    :param unprobed: Declared owner tickets of open paths no probe measures.
    """

    probed: tuple[str, ...]
    unprobed: tuple[str, ...]


# Rows are append-only per revision. Only a change to a gate row needs a new one: an in-sandbox
# pin's state or owner, or a probed sandbox rule; checks run outside the sandbox never do. A server
# change that widens a step's reach deletes older rows; a server-code blocker stays until fixed.
SEATBELT_1 = HostSandboxPolicy("seatbelt", "1")
BWRAP_1 = HostSandboxPolicy("bwrap", "1")
# Revision 2: seatbelt refuses other programs' Unix-domain sockets; bwrap's rules are unchanged.
SEATBELT_2 = HostSandboxPolicy("seatbelt", "2")
BWRAP_2 = HostSandboxPolicy("bwrap", "2")
# The owners of the open pins in probe 15's tests, per policy they were measured at.
IDENTITY_PROBE_OPEN: Mapping[HostSandboxPolicy, tuple[str, ...]] = MappingProxyType(
    {
        # Other programs' sockets and loopback services; a planted repository config.
        SEATBELT_1: ("CRL-174", "CRL-181"),
        BWRAP_1: ("CRL-174", "CRL-181"),
        # Other programs' loopback services; a Unix-domain socket inside the step's own
        # worktree and, on Linux, abstract ones; a planted repository config.
        SEATBELT_2: ("CRL-201", "CRL-203", "CRL-181"),
        BWRAP_2: ("CRL-201", "CRL-202", "CRL-203", "CRL-181"),
    }
)
# Open owner paths the probe does not measure; each leaves only when it is closed.
UNPROBED_BLOCKERS: Mapping[HostSandboxPolicy, tuple[str, ...]] = MappingProxyType(
    {
        SEATBELT_1: (
            "CRL-170",  # no CI runs macOS; an OS or CLI update can void a seatbelt rule
            "CRL-171",  # Mach services, the clipboard and Spotlight are not measured
            "CRL-181",  # files a step leaves that the owner's tools run, beyond the plant
            "CRL-193",  # the label does not see the owner's other or earlier runs
            "CRL-195",  # a step that reaches the server can guess the owner's password
        ),
        BWRAP_1: ("CRL-181", "CRL-193", "CRL-195"),
        # As at revision 1, none of them closed with it; and masked files a step can still
        # read by renaming their parent directory.
        SEATBELT_2: ("CRL-170", "CRL-171", "CRL-181", "CRL-193", "CRL-195", "CRL-204"),
        BWRAP_2: ("CRL-181", "CRL-193", "CRL-195", "CRL-204"),
    }
)


def blocker_table(
    probed: Mapping[HostSandboxPolicy, tuple[str, ...]],
    unprobed: Mapping[HostSandboxPolicy, tuple[str, ...]],
) -> Mapping[HostSandboxPolicy, SandboxBlockers]:
    """A row for each policy with both parts recorded; one missing either part reads unknown."""
    return MappingProxyType(
        {
            policy: SandboxBlockers(blockers, unprobed[policy])
            for policy, blockers in probed.items()
            if policy in unprobed
        }
    )


GATE_BLOCKERS = blocker_table(IDENTITY_PROBE_OPEN, UNPROBED_BLOCKERS)


@dataclass(frozen=True)
class ServerConfigFacts:
    """
    Server settings that would hand a step an owner credential; ``None`` where unread.

    :param runner_token_allow_listed: The server keeps an allow-listed runner token.
    :param machine_client: A machine client may mint delegated tokens.
    :param device_grant: The device authorization grant is on.
    :param state_under_step_read_root: The server's data dir, artifact location, config file
        or a database file is under a path the seatbelt sandbox lets every step read, or one
        of them could not be placed.
    :param local_single_user: The single-user marker is set, which the probe never ran with.
    """

    runner_token_allow_listed: bool | None = None
    machine_client: bool | None = None
    device_grant: bool | None = None
    state_under_step_read_root: bool | None = None
    local_single_user: bool | None = None

    @property
    def verified(self) -> bool:
        """Every setting is read and off."""
        return all(value is False for value in astuple(self))


@dataclass(frozen=True)
class GateIntegrityFacts:
    """
    What the label is computed from; every fact left out is unknown.

    :param server_mode: The server's sign-in mode, e.g. ``"accounts"`` or ``"header"``.
    :param native_steps_enabled: Whether this server process creates claude-native steps.
    :param host_sandbox: The run's own host's sandbox policy, as its owner's host reports it.
    """

    server_mode: str | None = None
    native_steps_enabled: bool | None = None
    server_config: ServerConfigFacts = field(default_factory=ServerConfigFacts)
    host_sandbox: HostSandboxPolicy | None = None


@dataclass(frozen=True)
class GateIntegrity:
    """A label and its reasons: none exactly when it is ``enforced``."""

    label: GateIntegrityLabel
    reasons: tuple[GateIntegrityReason, ...]


def gate_integrity(
    facts: GateIntegrityFacts,
    table: Mapping[HostSandboxPolicy, SandboxBlockers] = GATE_BLOCKERS,
) -> GateIntegrity:
    """
    The label the facts allow: ``enforced`` only with no reason, each reason once, in order.

    :param table: The blockers per sandbox policy; a policy it lacks is unknown.
    """
    host = facts.host_sandbox
    blockers = None if host is None else table.get(host)
    applies = {
        GateIntegrityReason.SERVER_MODE_NOT_VERIFIED: (
            facts.server_mode not in VERIFIED_SERVER_MODES
        ),
        GateIntegrityReason.SERVER_CONFIG_NOT_VERIFIED: not facts.server_config.verified,
        GateIntegrityReason.NATIVE_STEPS_ENABLED: facts.native_steps_enabled is not False,
        GateIntegrityReason.HOST_SANDBOX_UNKNOWN: blockers is None,
        GateIntegrityReason.HOST_SANDBOX_OPEN: (
            blockers is not None and bool(blockers.probed or blockers.unprobed)
        ),
    }
    reasons = tuple(reason for reason in REASONS if applies[reason])
    return GateIntegrity(label="not_enforced" if reasons else "enforced", reasons=reasons)

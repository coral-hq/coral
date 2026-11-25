"""The gate-integrity label: ``enforced`` only when every fact is known and nothing blocks it."""

from __future__ import annotations

import dataclasses
import itertools
import re
from collections.abc import Mapping

import pytest

from coral.gates.integrity import (
    GATE_BLOCKERS,
    IDENTITY_PROBE_OPEN,
    REASONS,
    UNPROBED_BLOCKERS,
    VERIFIED_SERVER_MODES,
    GateIntegrity,
    GateIntegrityFacts,
    GateIntegrityReason,
    HostSandboxPolicy,
    SandboxBlockers,
    ServerConfigFacts,
    blocker_table,
    gate_integrity,
)

SEATBELT = HostSandboxPolicy("seatbelt", "1")
BWRAP = HostSandboxPolicy("bwrap", "1")
SEATBELT_2 = HostSandboxPolicy("seatbelt", "2")
BWRAP_2 = HostSandboxPolicy("bwrap", "2")
VERIFIED_CONFIG = ServerConfigFacts(
    runner_token_allow_listed=False,
    machine_client=False,
    device_grant=False,
    state_under_step_read_root=False,
    local_single_user=False,
)
# Every fact the label can verify: only the host's sandbox is left to decide it.
VERIFIED = GateIntegrityFacts(
    server_mode="accounts",
    native_steps_enabled=False,
    server_config=VERIFIED_CONFIG,
    host_sandbox=SEATBELT,
)
NOTHING_OPEN = SandboxBlockers(probed=(), unprobed=())
CLOSED_TABLE: Mapping[HostSandboxPolicy, SandboxBlockers] = {
    SEATBELT: NOTHING_OPEN,
    BWRAP: NOTHING_OPEN,
}
TABLES: dict[str, Mapping[HostSandboxPolicy, SandboxBlockers]] = {
    "closed": CLOSED_TABLE,
    "probed_open": {**CLOSED_TABLE, SEATBELT: SandboxBlockers(("CRL-174",), ())},
    "unprobed_open": {**CLOSED_TABLE, BWRAP: SandboxBlockers((), ("CRL-193",))},
    "today": GATE_BLOCKERS,
}
SERVER_MODES = ("accounts", "oidc", "header", "custom", "none", "Accounts", None)
CONFIG_VALUES = (False, True, None)
HOSTS = (
    SEATBELT,
    BWRAP,
    SEATBELT_2,
    BWRAP_2,
    # A revision no table has a row for.
    HostSandboxPolicy("seatbelt", "0"),
    HostSandboxPolicy("none", "1"),
    HostSandboxPolicy("jail", "1"),
    None,
)
TICKET = re.compile(r"^CRL-[1-9][0-9]*$")


def _expected(
    facts: GateIntegrityFacts, table: Mapping[HostSandboxPolicy, SandboxBlockers]
) -> tuple[GateIntegrityReason, ...]:
    """The reasons the rule names, written out one condition per reason."""
    config = dataclasses.astuple(facts.server_config)
    entry = table.get(facts.host_sandbox) if facts.host_sandbox is not None else None
    applies = {
        "server_mode_not_verified": facts.server_mode != "accounts",
        "server_config_not_verified": any(value is not False for value in config),
        "native_steps_enabled": facts.native_steps_enabled is not False,
        "host_sandbox_unknown": entry is None,
        "host_sandbox_open": entry is not None and bool(entry.probed or entry.unprobed),
    }
    # Written in the order the API documents them.
    assert list(applies) == list(REASONS)
    return tuple(GateIntegrityReason(reason) for reason, holds in applies.items() if holds)


def _configs() -> list[ServerConfigFacts]:
    """Every config verified, and each fact alone on or unknown."""
    names = [field.name for field in dataclasses.fields(ServerConfigFacts)]
    return [
        VERIFIED_CONFIG,
        *(
            dataclasses.replace(VERIFIED_CONFIG, **{name: value})
            for name, value in itertools.product(names, (True, None))
        ),
    ]


def test_enforced_only_on_an_accounts_server_with_every_fact_verified_and_nothing_open() -> None:
    enforced = []
    for mode, native, config, host, (table_name, table) in itertools.product(
        SERVER_MODES, CONFIG_VALUES, _configs(), HOSTS, TABLES.items()
    ):
        facts = GateIntegrityFacts(
            server_mode=mode, native_steps_enabled=native, server_config=config, host_sandbox=host
        )
        result = gate_integrity(facts, table)
        expected = _expected(facts, table)
        assert result.reasons == expected, (facts, table_name)
        # Each reason at most once, in the declared order, and enforced exactly without one.
        assert list(result.reasons) == sorted(set(result.reasons), key=REASONS.index)
        assert (result.label == "enforced") == (not result.reasons), (facts, table_name)
        if result.label == "enforced":
            enforced.append((facts, table_name))
    # Only verified facts on a sandbox whose table entry is empty ever read enforced.
    on_bwrap = dataclasses.replace(VERIFIED, host_sandbox=BWRAP)
    assert enforced == [
        (VERIFIED, "closed"),
        (VERIFIED, "unprobed_open"),
        (on_bwrap, "closed"),
        (on_bwrap, "probed_open"),
    ]


def test_every_fact_left_unknown_names_every_reason_but_an_open_sandbox() -> None:
    result = gate_integrity(GateIntegrityFacts())

    assert result == GateIntegrity(
        label="not_enforced",
        reasons=(
            "server_mode_not_verified",
            "server_config_not_verified",
            "native_steps_enabled",
            "host_sandbox_unknown",
        ),
    )
    # The same facts always give the same label.
    assert gate_integrity(GateIntegrityFacts()) == result


@pytest.mark.parametrize(
    ("case", "change", "reason"),
    [
        ("single-user or proxy header", {"server_mode": "header"}, "server_mode_not_verified"),
        ("oidc sign-in", {"server_mode": "oidc"}, "server_mode_not_verified"),
        ("embedding app's provider", {"server_mode": "custom"}, "server_mode_not_verified"),
        ("authentication off", {"server_mode": "none"}, "server_mode_not_verified"),
        ("unread server mode", {"server_mode": None}, "server_mode_not_verified"),
        ("native steps on", {"native_steps_enabled": True}, "native_steps_enabled"),
        ("native steps unread", {"native_steps_enabled": None}, "native_steps_enabled"),
        (
            "allow-listed runner token",
            {
                "server_config": dataclasses.replace(
                    VERIFIED_CONFIG, runner_token_allow_listed=True
                )
            },
            "server_config_not_verified",
        ),
        (
            "machine client",
            {"server_config": dataclasses.replace(VERIFIED_CONFIG, machine_client=True)},
            "server_config_not_verified",
        ),
        (
            "device grant",
            {"server_config": dataclasses.replace(VERIFIED_CONFIG, device_grant=True)},
            "server_config_not_verified",
        ),
        (
            "single-user marker on the server",
            {"server_config": dataclasses.replace(VERIFIED_CONFIG, local_single_user=True)},
            "server_config_not_verified",
        ),
        (
            "state under a step read root",
            {
                "server_config": dataclasses.replace(
                    VERIFIED_CONFIG, state_under_step_read_root=True
                )
            },
            "server_config_not_verified",
        ),
        ("host offline or another owner's", {"host_sandbox": None}, "host_sandbox_unknown"),
        (
            "unknown policy revision",
            {"host_sandbox": HostSandboxPolicy("seatbelt", "0")},
            "host_sandbox_unknown",
        ),
        (
            "no OS sandbox",
            {"host_sandbox": HostSandboxPolicy("none", "1")},
            "host_sandbox_unknown",
        ),
    ],
)
def test_each_unverified_fact_alone_keeps_a_closed_table_not_enforced(
    case: str, change: dict[str, object], reason: GateIntegrityReason
) -> None:
    result = gate_integrity(dataclasses.replace(VERIFIED, **change), CLOSED_TABLE)

    assert result == GateIntegrity(label="not_enforced", reasons=(reason,)), case


@pytest.mark.parametrize("policy", sorted(GATE_BLOCKERS, key=repr))
def test_today_no_sandbox_is_verified_even_with_every_other_fact(
    policy: HostSandboxPolicy,
) -> None:
    result = gate_integrity(dataclasses.replace(VERIFIED, host_sandbox=policy))

    assert result == GateIntegrity(label="not_enforced", reasons=("host_sandbox_open",))


def test_the_table_has_both_parts_for_each_measured_policy() -> None:
    assert set(GATE_BLOCKERS) == set(IDENTITY_PROBE_OPEN) == set(UNPROBED_BLOCKERS)
    assert set(GATE_BLOCKERS) == {SEATBELT, BWRAP, SEATBELT_2, BWRAP_2}
    for policy, blockers in GATE_BLOCKERS.items():
        assert blockers == SandboxBlockers(IDENTITY_PROBE_OPEN[policy], UNPROBED_BLOCKERS[policy])
        tickets = (*blockers.probed, *blockers.unprobed)
        assert all(TICKET.fullmatch(ticket) for ticket in tickets), policy
        assert len(set(blockers.probed)) == len(blockers.probed), policy
        assert len(set(blockers.unprobed)) == len(blockers.unprobed), policy


def test_the_declared_blockers_are_the_open_paths_no_probe_measures() -> None:
    # Dropping one needs this list and the table to change together.
    assert UNPROBED_BLOCKERS == {
        SEATBELT: ("CRL-170", "CRL-171", "CRL-181", "CRL-193", "CRL-195"),
        BWRAP: ("CRL-181", "CRL-193", "CRL-195"),
        SEATBELT_2: ("CRL-170", "CRL-171", "CRL-181", "CRL-193", "CRL-195", "CRL-204"),
        BWRAP_2: ("CRL-181", "CRL-193", "CRL-195", "CRL-204"),
    }


# Every row the table has recorded, changed only by the rule above the table in
# coral/gates/integrity.py (a new revision, a widening server change, a server-code blocker's fix).
RECORDED_ROWS = {
    HostSandboxPolicy("seatbelt", "1"): SandboxBlockers(
        probed=("CRL-174", "CRL-181"),
        unprobed=("CRL-170", "CRL-171", "CRL-181", "CRL-193", "CRL-195"),
    ),
    HostSandboxPolicy("bwrap", "1"): SandboxBlockers(
        probed=("CRL-174", "CRL-181"), unprobed=("CRL-181", "CRL-193", "CRL-195")
    ),
    HostSandboxPolicy("seatbelt", "2"): SandboxBlockers(
        probed=("CRL-201", "CRL-203", "CRL-181"),
        unprobed=("CRL-170", "CRL-171", "CRL-181", "CRL-193", "CRL-195", "CRL-204"),
    ),
    HostSandboxPolicy("bwrap", "2"): SandboxBlockers(
        probed=("CRL-201", "CRL-202", "CRL-203", "CRL-181"),
        unprobed=("CRL-181", "CRL-193", "CRL-195", "CRL-204"),
    ),
}


def test_every_recorded_row_stays_as_it_was_recorded() -> None:
    assert dict(GATE_BLOCKERS) == RECORDED_ROWS
    # Recorded in the order the revisions were added: a new one never moves an older row.
    assert list(GATE_BLOCKERS) == list(RECORDED_ROWS)


# A server on code older than revision 2 holds only the rows recorded before it.
REVISION_1_ROWS = {policy: row for policy, row in RECORDED_ROWS.items() if policy.revision == "1"}


@pytest.mark.parametrize("backend", ["seatbelt", "bwrap"])
@pytest.mark.parametrize(
    ("host_revision", "server_rows", "reason"),
    [
        pytest.param("1", REVISION_1_ROWS, "host_sandbox_open", id="old-host-old-server"),
        pytest.param("1", GATE_BLOCKERS, "host_sandbox_open", id="old-host-new-server"),
        pytest.param("2", GATE_BLOCKERS, "host_sandbox_open", id="new-host-new-server"),
        pytest.param("2", REVISION_1_ROWS, "host_sandbox_unknown", id="new-host-old-server"),
        pytest.param("3", GATE_BLOCKERS, "host_sandbox_unknown", id="later-host"),
        pytest.param("", GATE_BLOCKERS, "host_sandbox_unknown", id="empty-revision"),
    ],
)
def test_every_mix_of_old_and_new_hosts_and_servers_is_not_enforced(
    backend: str,
    host_revision: str,
    server_rows: Mapping[HostSandboxPolicy, SandboxBlockers],
    reason: GateIntegrityReason,
) -> None:
    host = HostSandboxPolicy(backend, host_revision)

    result = gate_integrity(dataclasses.replace(VERIFIED, host_sandbox=host), server_rows)

    assert result == GateIntegrity(label="not_enforced", reasons=(reason,))


def test_a_policy_missing_either_part_has_no_row_and_reads_unknown() -> None:
    lone = HostSandboxPolicy("seatbelt", "9")
    for probed, unprobed in (
        ({**IDENTITY_PROBE_OPEN, lone: ()}, UNPROBED_BLOCKERS),
        (IDENTITY_PROBE_OPEN, {**UNPROBED_BLOCKERS, lone: ()}),
    ):
        table = blocker_table(probed, unprobed)
        assert set(table) == set(GATE_BLOCKERS)
        result = gate_integrity(dataclasses.replace(VERIFIED, host_sandbox=lone), table)
        assert result.reasons == ("host_sandbox_unknown",)


def test_only_accounts_sign_in_can_be_verified() -> None:
    # Header (single-user or behind a proxy), OIDC and custom sign-in never qualify.
    assert {"accounts"} == VERIFIED_SERVER_MODES

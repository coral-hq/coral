"""The done-when evaluator: final pass after the last change."""

from __future__ import annotations

import os
import random

import pytest

from coral.evidence.evaluate import evaluate
from coral.evidence.ir import (
    CommandObservation,
    EvidenceRequirement,
    InProgress,
    Missing,
    Pass,
    RequiredCommand,
)
from coral.evidence.messages import verdict_message

TESTS = RequiredCommand(item_id="tests", run="pytest -q")
FORMAT = RequiredCommand(item_id="format", run="ruff format", may_modify=True, allow_args=True)
REQUIREMENT = EvidenceRequirement(items=(TESTS,))


class _Log:
    """Builds one session's observations in order."""

    def __init__(self) -> None:
        self.items: list[CommandObservation] = []

    def shell(
        self,
        command: str,
        l1: str | None,
        *,
        exit_code: int | None = 0,
        timed_out: bool = False,
    ) -> _Log:
        self.items.append(
            CommandObservation(
                session_id="s1",
                op_key=f"op{len(self.items)}",
                obs_seq=len(self.items) + 1,
                tool="shell",
                command=command,
                exit_code=exit_code,
                timed_out=timed_out,
                l1_after=l1,
            )
        )
        return self

    def edit(self, path: str) -> _Log:
        self.items.append(
            CommandObservation(
                session_id="s1",
                op_key=f"op{len(self.items)}",
                obs_seq=len(self.items) + 1,
                tool="edit",
                changed_path=path,
            )
        )
        return self


def _reasons(verdict: object) -> list[tuple[str, str, str | None]]:
    assert isinstance(verdict, Missing)
    return [(item.item_id, item.reason, item.changed_path) for item in verdict.items]


def test_tests_after_the_last_edit_pass() -> None:
    log = _Log().edit("api/users.py").shell("pytest -q", "B")
    assert evaluate(REQUIREMENT, log.items, submit_l1="B") == Pass()


def test_an_edit_after_the_tests_fails_naming_the_path() -> None:
    log = _Log().shell("pytest -q", "A").edit("api/users.py").shell("git status", "B")
    verdict = evaluate(REQUIREMENT, log.items, submit_l1="B")
    assert _reasons(verdict) == [("tests", "predates_change", "api/users.py")]
    assert "ran before the last change to `api/users.py`" in verdict_message(verdict)


def test_a_rerun_after_the_edit_passes() -> None:
    log = _Log().shell("pytest -q", "A").edit("api/users.py").shell("pytest -q", "B")
    assert evaluate(REQUIREMENT, log.items, submit_l1="B") == Pass()


def test_a_shell_edit_after_the_tests_fails() -> None:
    log = _Log().shell("pytest -q", "A").shell("sed -i s/a/b/ api/users.py", "B")
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="B")) == [
        ("tests", "predates_change", None)
    ]


def test_a_change_outside_the_tools_is_seen_at_submit() -> None:
    log = _Log().shell("pytest -q", "A")
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="Z")) == [
        ("tests", "predates_change", None)
    ]


def test_a_formatter_that_may_modify_after_the_tests_still_passes() -> None:
    requirement = EvidenceRequirement(items=(TESTS, FORMAT))
    log = _Log().shell("pytest -q", "A").shell("ruff format .", "B")
    assert evaluate(requirement, log.items, submit_l1="B") == Pass()


def test_formatter_then_tests_passes() -> None:
    requirement = EvidenceRequirement(items=(FORMAT, TESTS))
    log = _Log().edit("a.py").shell("ruff format . && pytest -q", "B")
    assert evaluate(requirement, log.items, submit_l1="B") == Pass()


def test_tests_that_change_the_tree_predate_their_own_change() -> None:
    log = _Log().shell("pytest -q", "A").shell("pytest -q", "B")
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="B")) == [
        ("tests", "predates_change", None)
    ]


def test_a_failing_rerun_after_the_change_fails() -> None:
    log = _Log().shell("pytest -q", "A").edit("a.py").shell("pytest -q", "B", exit_code=1)
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="B")) == [("tests", "failed", None)]


def test_a_timeout_is_exit_unknown() -> None:
    log = _Log().shell("pytest -q", "A", exit_code=None, timed_out=True)
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="A")) == [
        ("tests", "exit_unknown", None)
    ]


def test_printed_output_and_or_true_never_count() -> None:
    log = _Log().shell("echo pytest -q passed", "A").shell("pytest -q || true", "A")
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="A")) == [
        ("tests", "never_ran", None)
    ]


def test_nothing_ran_is_never_ran() -> None:
    assert _reasons(evaluate(REQUIREMENT, [], submit_l1="A")) == [("tests", "never_ran", None)]


def test_an_unknown_fingerprint_after_a_run_is_a_change() -> None:
    log = _Log().shell("pytest -q", "A").shell("make build", None)
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="A")) == [
        ("tests", "predates_change", None)
    ]


def test_lagging_capture_or_no_submit_fingerprint_is_in_progress() -> None:
    log = _Log().shell("pytest -q", "A")
    assert isinstance(
        evaluate(REQUIREMENT, log.items, submit_l1="A", in_progress="calls in flight"),
        InProgress,
    )
    assert isinstance(evaluate(REQUIREMENT, log.items, submit_l1=None), InProgress)


def test_a_duplicate_op_key_leaves_the_verdict_unchanged() -> None:
    log = _Log().shell("pytest -q", "A").edit("a.py").shell("pytest -q", "B")
    duplicate = log.items[0].model_copy(update={"obs_seq": 99, "l1_after": "C"})
    once = evaluate(REQUIREMENT, log.items, submit_l1="B")
    twice = evaluate(REQUIREMENT, [*log.items, duplicate], submit_l1="B")
    assert once == twice == Pass()


def test_evaluation_is_deterministic() -> None:
    log = _Log().shell("pytest -q", "A").edit("a.py")
    first = evaluate(REQUIREMENT, log.items, submit_l1="B")
    assert first == evaluate(REQUIREMENT, list(reversed(log.items)), submit_l1="B")
    assert isinstance(first, Missing)
    assert verdict_message(first) == verdict_message(first)


def _seeds() -> list[int]:
    raw = os.environ.get("CORAL_FUZZ_SEEDS", "1,2,3,4,5,6,7,8")
    return [int(seed) for seed in raw.split(",") if seed.strip()]


@pytest.mark.parametrize("seed", _seeds())
def test_seeded_sequences_pass_only_when_a_clean_run_follows_the_last_change(seed: int) -> None:
    rng = random.Random(seed)
    for _ in range(200):
        log = _Log()
        l1 = 0
        last_change = -1
        last_good_run = -2
        for _step in range(rng.randint(0, 8)):
            choice = rng.random()
            if choice < 0.3:
                log.edit(f"f{rng.randint(1, 3)}.py")
                l1 += 1
                last_change = len(log.items) - 1
            elif choice < 0.7:
                code = rng.choice([0, 0, 1])
                log.shell("pytest -q", str(l1), exit_code=code)
                if code == 0:
                    last_good_run = len(log.items) - 1
                else:
                    last_good_run = -2
            else:
                log.shell("ls", str(l1))
        verdict = evaluate(REQUIREMENT, log.items, submit_l1=str(l1))
        assert (verdict == Pass()) == (last_good_run > last_change), log.items


def test_a_command_after_the_tests_disqualifies_the_line() -> None:
    log = _Log().shell("mv tests/a.py /tmp/a.py && pytest -q && mv /tmp/a.py tests/a.py", "A")
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="A")) == [
        ("tests", "never_ran", None)
    ]


def test_a_may_modify_command_absorbs_only_its_own_line() -> None:
    requirement = EvidenceRequirement(items=(TESTS, FORMAT))
    log = _Log().shell("pytest -q", "A").shell("touch src/x.py && ruff format .", "B")
    assert _reasons(evaluate(requirement, log.items, submit_l1="B")) == [
        ("tests", "predates_change", None),
        ("format", "predates_change", None),
    ]


def test_an_unreadable_tree_after_the_tests_is_unverified() -> None:
    log = _Log().shell("pytest -q", None)
    assert _reasons(evaluate(REQUIREMENT, log.items, submit_l1="A")) == [
        ("tests", "unverified", None)
    ]

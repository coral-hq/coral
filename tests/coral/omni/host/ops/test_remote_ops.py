"""Host ``fetch_ref`` and consented ``push`` refuse bad refs and missing consent."""

from __future__ import annotations

from pathlib import Path

import pytest

from coral.omni.host.ops import _remote_ops
from coral.workspace.consent import PushConsent, consent_digest
from tests.coral.omni.host.ops._worktrees import (
    LinkedWorktree,
    expect_op_error,
    make_linked_worktree,
    op_request,
)


@pytest.fixture
def worktree(tmp_path: Path) -> LinkedWorktree:
    return make_linked_worktree(tmp_path)


@pytest.fixture
def handlers():
    return _remote_ops.remote_handlers()


def test_push_without_consent_digest_is_refused(worktree: LinkedWorktree, handlers) -> None:
    expect_op_error(
        lambda: handlers["push"](
            op_request(
                "push",
                worktree,
                remote="origin",
                refspec="refs/heads/coral/r-0123456789ab/fix:refs/heads/coral/r-0123456789ab/fix",
                consent_digest="",
            )
        ),
        "workspace.push_not_permitted",
        permanent=True,
    )


def test_push_with_malformed_consent_is_not_permitted(worktree: LinkedWorktree, handlers) -> None:
    expect_op_error(
        lambda: handlers["push"](
            op_request(
                "push",
                worktree,
                remote="origin",
                refspec="refs/heads/coral/r-0123456789ab/fix:refs/heads/coral/r-0123456789ab/fix",
                consent_digest="not-a-digest",
            )
        ),
        "workspace.push_not_permitted",
        permanent=True,
    )


def test_push_outside_run_prefix_is_invalid_ref(worktree: LinkedWorktree, handlers) -> None:
    digest = consent_digest(
        PushConsent(
            run_id="run-1",
            remote="origin",
            ref_prefix="refs/heads/coral/r-0123456789ab/",
            granted_by="alice",
            granted_at=1,
        )
    )
    expect_op_error(
        lambda: handlers["push"](
            op_request(
                "push",
                worktree,
                remote="origin",
                refspec="refs/heads/main:refs/heads/main",
                consent_digest=digest,
            )
        ),
        "workspace.invalid_ref",
        permanent=True,
    )


def test_fetch_ref_outside_fetch_namespace_is_invalid(worktree: LinkedWorktree, handlers) -> None:
    expect_op_error(
        lambda: handlers["fetch_ref"](
            op_request(
                "fetch_ref",
                worktree,
                remote="origin",
                refspec="refs/heads/main",
                dest_ref="refs/heads/coral/r-0123456789ab/stolen",
            )
        ),
        "workspace.invalid_ref",
        permanent=True,
    )


def test_remote_handlers_are_registered() -> None:
    names = set(_remote_ops.remote_handlers())
    assert names == {"fetch_ref", "push"}

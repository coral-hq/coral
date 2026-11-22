"""Host-channel ``fetch_ref`` and consented ``push`` (WSP-07).

Writes only under ``refs/coral/fetch/<run12>/`` (fetch) or
``refs/heads/coral/r-<run12>/*`` (push). Push requires ``consent_digest`` matching
the per-run grant; without it the host returns ``workspace.push_not_permitted``.
"""

from __future__ import annotations

import functools
import re
import time
from collections.abc import Callable, Mapping

from coral.omni.host.ops._git import Git
from coral.omni.host.ops._locks import one_op_per_worktree
from coral.omni.host.ops._target import invalid_params, op_params, pinned
from coral.workspace.ops import INVALID_REF, PUSH_NOT_PERMITTED, validate_coral_ref
from omnigent.host.workspace_ops import (
    WorkspaceOpHandler,
    WorkspaceOpHandlerError,
    WorkspaceOpRequest,
)

# Push destinations: refs/heads/coral/r-<12 hex>/*
_PUSH_REF = re.compile(r"^refs/heads/coral/r-[0-9a-f]{12}/")
# Fetch destinations: refs/coral/fetch/<12 hex>/
_FETCH_REF = re.compile(r"^refs/coral/fetch/[0-9a-f]{12}/")
_CONSENT_DIGEST = re.compile(r"[0-9a-f]{64}")
_REMOTE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}")

Sleep = Callable[[float], None]


def remote_handlers(*, sleep: Sleep = time.sleep) -> dict[str, WorkspaceOpHandler]:
    """``fetch_ref`` and ``push`` handlers by op name."""
    return {
        "fetch_ref": one_op_per_worktree(functools.partial(_fetch_ref, sleep=sleep)),
        "push": one_op_per_worktree(functools.partial(_push, sleep=sleep)),
    }


def _fetch_ref(request: WorkspaceOpRequest, *, sleep: Sleep) -> Mapping[str, object]:
    """Fetch ``refspec`` from ``remote`` into a ``refs/coral/fetch/<run12>/`` dest."""
    params = op_params(request, required=("remote", "refspec", "dest_ref"))
    remote = _remote_name(params["remote"])
    refspec = _text(params["refspec"], "refspec", max_len=512)
    dest = _text(params["dest_ref"], "dest_ref", max_len=255)
    if not _FETCH_REF.match(dest):
        raise WorkspaceOpHandlerError(
            INVALID_REF,
            f"fetch destination must be under refs/coral/fetch/<run12>/, got {dest[:64]!r}",
            permanent=True,
        )
    try:
        validate_coral_ref(dest)
    except ValueError as exc:
        raise WorkspaceOpHandlerError(INVALID_REF, str(exc), permanent=True) from None
    with pinned(request, params, write=True) as target:
        git = _git(target.git, sleep)
        # +src:dest updates dest; never force outside the fetch namespace.
        mapped = f"+{refspec}:{dest}"
        git.run("fetch", "--no-tags", remote, mapped)
        oid = git.run("rev-parse", "--verify", dest).stdout.decode().strip()
        return {"dest_ref": dest, "commit": oid}


def _push(request: WorkspaceOpRequest, *, sleep: Sleep) -> Mapping[str, object]:
    """Push ``refspec`` to ``remote`` only when ``consent_digest`` is present and hex."""
    params = op_params(
        request, required=("remote", "refspec", "consent_digest"), optional=("force_with_lease",)
    )
    remote = _remote_name(params["remote"])
    refspec = _text(params["refspec"], "refspec", max_len=512)
    digest = params["consent_digest"]
    if not isinstance(digest, str) or not _CONSENT_DIGEST.fullmatch(digest):
        raise WorkspaceOpHandlerError(
            PUSH_NOT_PERMITTED,
            "Push is not permitted for this run",
            permanent=True,
        )
    # Local side of refspec must be a coral run branch (src:dst or bare src).
    local = refspec.split(":", 1)[0].lstrip("+")
    if local.startswith("refs/"):
        full = local
    else:
        full = f"refs/heads/{local}"
    if not _PUSH_REF.match(full):
        raise WorkspaceOpHandlerError(
            INVALID_REF,
            f"push may only send refs/heads/coral/r-<run12>/*, got {full[:64]!r}",
            permanent=True,
        )
    try:
        validate_coral_ref(full)
    except ValueError as exc:
        raise WorkspaceOpHandlerError(INVALID_REF, str(exc), permanent=True) from None
    force = params.get("force_with_lease", True)
    if not isinstance(force, bool):
        raise invalid_params("force_with_lease must be a boolean")
    with pinned(request, params, write=True) as target:
        git = _git(target.git, sleep)
        argv = ["push", "--no-thin"]
        if force:
            argv.append("--force-with-lease")
        argv.extend((remote, refspec))
        git.run(*argv)
        return {"remote": remote, "refspec": refspec, "consent_digest": digest}


def _git(git: Git, sleep: Sleep) -> Git:
    from dataclasses import replace

    return replace(git, sleep=sleep)


def _remote_name(value: object) -> str:
    if not isinstance(value, str) or not _REMOTE.fullmatch(value):
        raise invalid_params("remote must be a simple remote name")
    return value


def _text(value: object, name: str, *, max_len: int) -> str:
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise invalid_params(f"{name} must be a non-empty string of at most {max_len} characters")
    return value


__all__ = ["remote_handlers"]

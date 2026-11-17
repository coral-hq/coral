"""Run worktrees on a user's connected host, without an HTTP request.

``connect_run_worktree_host`` checks that the run owner may use the host before
any frame reaches it (``host_access``), then returns a ``RunWorktreeHost`` for
``coral.workspace.run_worktree``. The adapter maps Omnigent's host proxies and
their errors onto that protocol. On every call it looks the live connection up
again, refuses one held by another owner or account registration, and sends the
frame under Omnigent's ``host_owner_scope``, so a replaced connection never
receives the run's frames.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import override

from coral.omni._upstream import (
    WorkspaceValidationError,
    WorktreeHostUnavailableError,
    WorktreeProxyError,
    _ask_host_stat,
    create_worktree_on_host,
    list_worktrees_on_host,
)
from coral.omni.server.host_access import HostAccessError, OwnerHost, authorize_owner_host
from coral.workspace.run_worktree import (
    CreatedRunWorktree,
    HostPathStat,
    HostWorktreeEntry,
    RunWorktreeError,
    RunWorktreeErrorCode,
    RunWorktreeHost,
    WorktreeCreateFailed,
    git_marker_path,
    truncate_host_message,
)
from omnigent.server.host_registry import HostConnection, HostRegistry
from omnigent.stores.host_store import HostStore


async def connect_run_worktree_host(
    *,
    host_registry: HostRegistry,
    host_store: HostStore,
    user_id: str | None,
    account_generation: str | None,
    host_id: str,
    workspace_id: int,
) -> RunWorktreeHost:
    """
    Authorize the run owner for the host from its stored row, then require a live connection.

    Callers (the run executor) take ``user_id``, ``account_generation`` and
    ``workspace_id`` from the stored run, never from a request.

    :param user_id: The run owner. ``None`` only when auth is disabled, which
        skips the owner and generation checks, as Omnigent does.
    :param account_generation: The owner's account registration saved with the
        run. A host row or connection from another registration of the same user
        id is refused, as ``fire.py`` refuses it for scheduled tasks.
    :param host_id: The host the run's repository is bound on.
    :param workspace_id: The tenant partition the host row and connection live in.
    :raises RunWorktreeError: ``not_permitted`` for an unknown host, another
        user's or registration's host, or a managed sandbox host, before any
        frame is sent; ``host_offline`` when the host has no live connection.
    """
    try:
        await authorize_owner_host(
            host_store=host_store,
            user_id=user_id,
            account_generation=account_generation,
            host_id=host_id,
            workspace_id=workspace_id,
        )
    except HostAccessError as exc:
        raise RunWorktreeError(exc.code, exc.message) from None
    run_host = _HostRunWorktreeHost(
        OwnerHost(
            host_registry=host_registry,
            host_id=host_id,
            workspace_id=workspace_id,
            user_id=user_id,
            account_generation=account_generation,
        )
    )
    run_host._connection()
    return run_host


class _HostRunWorktreeHost(RunWorktreeHost):
    """
    ``RunWorktreeHost`` over one host's live connection, for one authorized owner.

    Private: only ``connect_run_worktree_host`` builds it, after the ownership check.
    """

    def __init__(self, owner_host: OwnerHost) -> None:
        self._owner_host = owner_host
        self._host_registry: HostRegistry = owner_host.host_registry

    def _connection(self) -> HostConnection:
        """
        The host's current connection, if the authorized owner still holds it.

        :raises RunWorktreeError: ``host_offline`` when there is none;
            ``not_permitted`` when another owner or registration holds it.
        """
        try:
            return self._owner_host.connection()
        except HostAccessError as exc:
            raise RunWorktreeError(exc.code, exc.message) from None

    def _lost_or_failed(self, conn: HostConnection, message: str) -> RunWorktreeError:
        """``host_offline`` once ``conn`` is no longer current, else ``worktree_failed``."""
        current = self._owner_host.current()
        code: RunWorktreeErrorCode = "host_offline" if current is not conn else "worktree_failed"
        return RunWorktreeError(code, truncate_host_message(message))

    @override
    async def stat(self, path: str) -> HostPathStat:
        conn = self._connection()
        try:
            with self._owner_host.owner_scope():
                result = await _ask_host_stat(
                    host_registry=self._host_registry, host_conn=conn, path=path
                )
        except WorkspaceValidationError as exc:
            # A stat also fails for a host-side error or a slow but connected host.
            raise self._lost_or_failed(conn, exc.message) from exc
        canonical_path = result.get("canonical_path")
        return HostPathStat(
            exists=result.get("exists") is True,
            is_directory=result.get("type") == "directory",
            canonical_path=canonical_path if isinstance(canonical_path, str) else None,
        )

    @override
    async def list_worktrees(self, repo_root: str) -> Sequence[HostWorktreeEntry]:
        conn = self._connection()
        try:
            with self._owner_host.owner_scope():
                listed = await list_worktrees_on_host(
                    host_registry=self._host_registry, host_conn=conn, repo_path=repo_root
                )
        except WorktreeHostUnavailableError as exc:
            # Raised for a lost connection and for a connected host that never answered.
            raise self._lost_or_failed(conn, exc.message) from exc
        except WorktreeProxyError as exc:
            raise await self._listing_failure(repo_root, exc) from exc
        entries: list[HostWorktreeEntry] = []
        for item in listed:
            path, branch = item.get("path"), item.get("branch")
            if isinstance(path, str):
                entries.append(
                    HostWorktreeEntry(
                        path=path,
                        branch=branch if isinstance(branch, str) else None,
                        is_main=item.get("is_main") is True,
                        # Older hosts send no lock state; only a real ``true`` counts.
                        locked=item.get("locked") is True,
                    )
                )
        return entries

    @override
    async def create_worktree(
        self, repo_root: str, branch: str, base_ref: str | None, *, existing_branch: bool
    ) -> CreatedRunWorktree:
        conn = self._connection()
        try:
            with self._owner_host.owner_scope():
                created = await create_worktree_on_host(
                    host_registry=self._host_registry,
                    host_conn=conn,
                    repo_path=repo_root,
                    branch_name=branch,
                    base_branch=base_ref,
                    existing_branch=existing_branch,
                )
        except WorktreeHostUnavailableError as exc:
            # Not a git failure. A late create may still finish; until it does (for good, if
            # git was killed) its worktree is locked, and later calls refuse, not adopt, it.
            raise self._lost_or_failed(conn, exc.message) from exc
        except WorktreeProxyError as exc:
            raise WorktreeCreateFailed(exc.message) from exc
        return CreatedRunWorktree(
            path=created.worktree_path, branch=created.branch, head_commit=created.head_commit
        )

    async def _listing_failure(self, repo_root: str, exc: WorktreeProxyError) -> RunWorktreeError:
        """
        Classify a failed listing of an existing directory without reading git's text.

        Every worktree root holds a ``.git`` entry, so without one there was no
        repository. An empty or junk ``.git`` directory, or a linked worktree whose
        main repository is gone, still reads as ``worktree_failed``.
        """
        git_entry = await self.stat(git_marker_path(repo_root))
        if not git_entry.exists:
            return RunWorktreeError("not_a_git_repo", f"{repo_root} is not a git repository")
        return RunWorktreeError("worktree_failed", truncate_host_message(exc.message))

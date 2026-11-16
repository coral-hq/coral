"""Coral's handlers for the host workspace-op channel (``omnigent.host_workspace_ops``).

The host loads :func:`workspace_op_handlers` through the entry point on its
first workspace-op frame, on its event loop. So this module stays import-light,
starts no process, and checks ``CORAL_DISABLE_HOST_ENTRY_POINTS`` before it
imports the handler modules. The handlers run git in the host's reaper guard.

Host tier: standard library, ``coral.workspace.ops``, ``coral.omni.process_map``
and public names of ``omnigent.host.workspace_ops`` only; never
``omnigent.server``, ``coral.db`` or ``coral.stores``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from coral.omni.process_map import host_entry_points_disabled

if TYPE_CHECKING:
    from omnigent.host.workspace_ops import WorkspaceOpHandler


def workspace_op_handlers() -> Mapping[str, WorkspaceOpHandler]:
    """Return Coral's handlers by op name; none when host entry points are disabled."""
    if host_entry_points_disabled():
        return {}
    from coral.omni.host.ops import _read_ops

    return {
        "head": _read_ops.head,
        "diff_stat": _read_ops.diff_stat,
        "read": _read_ops.read,
        "fingerprint": _read_ops.fingerprint,
    }

"""Loading and running Coral's host handlers keeps the host free of database modules."""

from __future__ import annotations

import tomllib
from pathlib import Path
from textwrap import dedent

from omnigent.host.workspace_ops import ENTRY_POINT_GROUP
from tests.coral.omni.host.ops._worktrees import LinkedWorktree
from tests.host.test_startup_imports import _run_without_database_imports

_REPO_ROOT = Path(__file__).resolve().parents[5]

# Modules the host must never load to serve Coral's workspace ops.
_FORBIDDEN_ON_THE_HOST = dedent("""\
    def assert_not_loaded(*prefixes):
        loaded = [
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)
        ]
        assert not loaded, loaded
    """)


def _declared_entry_point() -> str:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["entry-points"][ENTRY_POINT_GROUP]["coral"]


def test_handlers_load_through_the_entry_point_and_run_without_database_modules(
    tmp_path: Path, worktree: LinkedWorktree
) -> None:
    code = _FORBIDDEN_ON_THE_HOST + dedent("""\
        import subprocess
        import time
        from importlib.metadata import EntryPoint
        from types import MappingProxyType

        from omnigent.host.workspace_ops import (
            ENTRY_POINT_GROUP,
            WorkspaceOpRequest,
            load_workspace_op_handlers,
        )

        value, root, repo_root, branch = sys.argv[1:]
        entry = EntryPoint(name="coral", value=value, group=ENTRY_POINT_GROUP)

        # The factory runs on the host's event loop: it must not start a process.
        real_popen = subprocess.Popen.__init__
        def no_process(*args, **kwargs):
            raise AssertionError("loading the handlers started a process")
        subprocess.Popen.__init__ = no_process
        handlers = load_workspace_op_handlers([entry])
        subprocess.Popen.__init__ = real_popen

        assert sorted(handlers) == ["diff_stat", "fingerprint", "head", "read"], dict(handlers)
        request = WorkspaceOpRequest(
            op="head",
            root=root,
            params=MappingProxyType({"repo_root": repo_root, "branch": branch}),
            timeout_s=60.0,
            op_key=None,
            deadline=time.monotonic() + 60.0,
        )
        assert handlers["head"](request)["branch"] == branch
        assert_not_loaded("omnigent.server", "coral.db", "coral.stores")
        """)

    _run_without_database_imports(
        tmp_path,
        code,
        _declared_entry_point(),
        str(worktree.root),
        str(worktree.repo_root),
        worktree.branch,
    )


def test_disabled_host_entry_points_serve_no_ops_and_import_no_handler_module(
    tmp_path: Path,
) -> None:
    code = _FORBIDDEN_ON_THE_HOST + dedent("""\
        import os

        os.environ["CORAL_DISABLE_HOST_ENTRY_POINTS"] = "1"
        from coral.omni.host.ops import workspace_op_handlers

        assert dict(workspace_op_handlers()) == {}
        assert_not_loaded(
            "coral.omni.host.ops._git",
            "coral.omni.host.ops._files",
            "coral.omni.host.ops._read_ops",
            "coral.omni.host.ops._target",
        )
        """)

    _run_without_database_imports(tmp_path, code)

"""A generated reviewer step cannot change files under the real OS sandbox; an implementer can.

Runs the real ``create_os_environment`` (bwrap on Linux, seatbelt on macOS) on
the os_env of bundles built by ``build_step_bundle_yaml``.
"""

from __future__ import annotations

import dataclasses
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

import omnigent
from coral.omni.server.bundles import pack_bundle
from coral.profiles.bundle_spec import Stance, StepRef, build_step_bundle_yaml
from omnigent.inner.datamodel import OSEnvSpec
from omnigent.inner.os_env import create_os_environment
from omnigent.server.bundles import validate_agent_bundle

_SANDBOX_BINARY = {"linux": "bwrap", "darwin": "sandbox-exec"}.get(sys.platform)

pytestmark = [
    pytest.mark.skipif(
        _SANDBOX_BINARY is None or shutil.which(_SANDBOX_BINARY) is None,
        reason="needs bwrap on Linux or sandbox-exec on macOS",
    ),
    pytest.mark.usefixtures("coral_policy_registry"),
]

ORIGINAL = "orig\n"


@pytest.fixture
def workspace() -> Iterator[Path]:
    # Under $HOME: pytest's tmp_path sits below /private/var/folders, which
    # seatbelt's defaults already cover, so it would hide missing grants.
    root = Path(tempfile.mkdtemp(prefix=".coral-reviewer-sandbox-", dir=Path.home()))
    (root / "existing.txt").write_text(ORIGINAL)
    yield root
    shutil.rmtree(root, ignore_errors=True)


def _step_os_env(stance: Stance, workspace: Path) -> OSEnvSpec:
    config_yaml = build_step_bundle_yaml(
        StepRef(workflow_id="demo.flow", node_id="check", roster_index=0),
        stance,
        model=None,
        provider=None,
    )
    os_env = validate_agent_bundle(pack_bundle(config_yaml)).os_env
    assert os_env is not None and os_env.sandbox is not None
    sandbox = os_env.sandbox
    package = Path(omnigent.__file__).resolve().parent
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        # Test-only read grant: an editable checkout lives outside the interpreter's
        # install root, and seatbelt refuses to import the sandbox helper from it.
        sandbox = dataclasses.replace(
            sandbox, read_paths=[*(sandbox.read_paths or []), str(package)]
        )
    return dataclasses.replace(os_env, cwd=str(workspace), sandbox=sandbox)


async def _try_to_write(stance: Stance, workspace: Path) -> dict[str, str]:
    env = create_os_environment(_step_os_env(stance, workspace))
    assert env is not None
    write = await env.write(path="new_write.txt", content="x")
    shell = await env.shell(command="echo x > owned.txt; echo rc=$?")
    append = await env.shell(command="echo appended >> existing.txt; echo rc=$?")
    return {"write": str(write), "shell": str(shell), "append": str(append)}


async def test_reviewer_writes_are_refused_by_the_os_sandbox(workspace: Path) -> None:
    results = await _try_to_write(Stance.REVIEWER, workspace)

    assert "blocked by sandbox" in results["write"]
    assert "rc=1" in results["shell"]
    assert "rc=1" in results["append"]
    assert sorted(p.name for p in workspace.iterdir()) == ["existing.txt"]
    assert (workspace / "existing.txt").read_text() == ORIGINAL


async def test_implementer_writes_succeed_in_the_same_workspace(workspace: Path) -> None:
    results = await _try_to_write(Stance.IMPLEMENTER, workspace)

    assert "rc=0" in results["shell"]
    assert "rc=0" in results["append"]
    assert (workspace / "new_write.txt").read_text() == "x"
    assert (workspace / "owned.txt").exists()
    assert (workspace / "existing.txt").read_text() == ORIGINAL + "appended\n"

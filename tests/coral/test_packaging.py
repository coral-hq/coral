"""Packaging smoke test and distribution-collision check (Spike 10)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tomllib
import zipfile
from importlib.metadata import EntryPoint, packages_distributions
from pathlib import Path

import click

from coral.omni.host.ops import workspace_op_handlers
from coral.omni.runner.tool_provider import tool_provider


def test_coral_package_has_no_conflicting_distribution() -> None:
    """No non-omnigent distribution claims the ``coral`` top-level package."""
    owners = packages_distributions().get("coral", [])
    assert set(owners) <= {"omnigent"}


def test_coral_declares_its_host_workspace_op_handlers() -> None:
    """The host loads Coral's workspace-op handlers from this entry point."""
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    group = pyproject["project"]["entry-points"]["omnigent.host_workspace_ops"]

    assert group == {"coral": "coral.omni.host.ops:workspace_op_handlers"}
    entry = EntryPoint(name="coral", value=group["coral"], group="omnigent.host_workspace_ops")
    assert entry.load() is workspace_op_handlers


def test_coral_declares_its_tool_provider() -> None:
    """Hosts and runners load Coral's engine tools and host token from this entry point."""
    pyproject = tomllib.loads((Path(__file__).resolve().parents[2] / "pyproject.toml").read_text())
    group = pyproject["project"]["entry-points"]["omnigent.tool_providers"]

    assert group == {"coral": "coral.omni.runner.tool_provider:tool_provider"}
    entry = EntryPoint(name="coral", value=group["coral"], group="omnigent.tool_providers")
    assert entry.load() is tool_provider


def test_built_wheel_runs_coral_help_in_no_deps_venv(tmp_path: Path) -> None:
    """Build a wheel without web UI and run ``coral --help`` with only click installed."""
    uv_bin = shutil.which("uv")
    assert uv_bin is not None, "uv executable must be on PATH"

    repo_root = Path(__file__).resolve().parents[2]
    wheel_dir = tmp_path / "dist"
    build_env = os.environ.copy()
    build_env["OMNIGENT_SKIP_WEB_UI"] = "true"

    subprocess.run(
        [
            uv_bin,
            "build",
            "--wheel",
            "--out-dir",
            str(wheel_dir),
        ],
        cwd=repo_root,
        env=build_env,
        check=True,
        capture_output=True,
        text=True,
    )
    wheels = list(wheel_dir.glob("omnigent-*.whl"))
    assert len(wheels) == 1
    with zipfile.ZipFile(wheels[0]) as wheel:
        seed_files = {
            name for name in wheel.namelist() if name.startswith("coral/profiles/seeds/")
        }
    assert {
        f"coral/profiles/seeds/{name}"
        for name in (
            "seeds.lock",
            "anchor.yaml",
            "orchestrator.yaml",
            "implementer.yaml",
            "reviewer.yaml",
        )
    } <= seed_files

    venv_dir = tmp_path / "venv"
    subprocess.run(
        [uv_bin, "venv", "--no-project", str(venv_dir)],
        check=True,
        capture_output=True,
        text=True,
    )
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [uv_bin, "pip", "install", "--python", str(venv_python), "--no-deps", str(wheels[0])],
        check=True,
        capture_output=True,
        text=True,
    )

    only_click_dir = tmp_path / "only_click"
    only_click_dir.mkdir()
    shutil.copytree(Path(click.__file__).resolve().parent, only_click_dir / "click")
    run_env = {
        "HOME": str(tmp_path / "home"),
        "PYTHONPATH": str(only_click_dir),
        "PATH": str(venv_python.parent),
    }
    coral_bin = venv_python.parent / ("coral.exe" if os.name == "nt" else "coral")
    result = subprocess.run(
        [str(coral_bin), "--help"],
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Coral workflow orchestration CLI." in result.stdout

    dist_check = subprocess.run(
        [
            str(venv_python),
            "-c",
            "from importlib.metadata import packages_distributions; "
            "dists = packages_distributions(); "
            "assert set(dists.get('coral', [])) == {'omnigent'}, f'got {dists.get(\"coral\")!r}'",
        ],
        env=run_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert dist_check.returncode == 0, dist_check.stderr

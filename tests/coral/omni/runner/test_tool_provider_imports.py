"""Coral's tool provider, loaded for a host's hello, pulls in only the standard library."""

from __future__ import annotations

import tomllib
from pathlib import Path
from textwrap import dedent

from omnigent.tools.extensions import ENTRY_POINT_GROUP
from tests.host.test_startup_imports import _run_without_database_imports

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _declared_entry_point() -> str:
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    return pyproject["project"]["entry-points"][ENTRY_POINT_GROUP]["coral"]


def test_entry_point_advertises_the_runner_token_without_database_modules(
    tmp_path: Path,
) -> None:
    code = dedent("""\
        import importlib.metadata

        value = sys.argv[1]
        group = "omnigent.tool_providers"
        discover = importlib.metadata.entry_points

        def installed(**params):
            if params.get("group") != group:
                return discover(**params)
            return [importlib.metadata.EntryPoint(name="coral", value=value, group=group)]

        importlib.metadata.entry_points = installed

        def loaded_outside(before, allowed):
            return sorted(
                name for name in set(sys.modules) - before
                if name.split(".")[0] not in sys.stdlib_module_names and name not in allowed
            )

        # The catalog and its schemas need only the standard library.
        before = set(sys.modules)
        import coral.tools.catalog
        extra = loaded_outside(
            before,
            {
                "coral", "coral.version",
                "coral.tools", "coral.tools.catalog", "coral.tools.schemas",
            },
        )
        assert not extra, extra

        from omnigent.host.frames import host_capabilities
        from omnigent.spec import AgentSpec
        from omnigent.tools.extensions import extension_host_capabilities, extension_tool_sets

        # Loading the provider and asking it for a Coral spec's tools adds only its own modules.
        before = set(sys.modules)
        assert extension_host_capabilities() == ("coral_runner:2", "coral_sandbox_policy:2")
        params = {"coral": {"generated": {"stance": "implementer"}}}
        tool_sets = extension_tool_sets(AgentSpec(spec_version=1, params=params))
        names = [tool["function"]["name"] for tool_set in tool_sets for tool in tool_set.tools]
        assert names == ["coral_submit_handoff", "coral_message_agent"], names
        extra = loaded_outside(
            before,
            {
                "coral.omni", "coral.omni.process_map",
                "coral.omni.runner", "coral.omni.runner.tool_provider",
            },
        )
        assert not extra, extra
        assert "coral.omni.runner.tool_provider" in sys.modules
        assert host_capabilities()[-2:] == ["coral_runner:2", "coral_sandbox_policy:2"], (
            host_capabilities()
        )
        """)

    _run_without_database_imports(tmp_path, code, _declared_entry_point())

"""The policy modules bundles name load on a runner without server or database modules."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from tests.host.test_startup_imports import _run_without_database_imports


def test_bundle_policy_modules_load_without_server_or_database_modules(tmp_path: Path) -> None:
    code = dedent("""\
        import importlib

        # A runner resolves every guardrail handler a bundle names before it starts the agent.
        for module in ("coral.omni.policies.guards", "coral.omni.policies.hygiene"):
            for entry in importlib.import_module(module).POLICY_REGISTRY:
                path, _, name = entry["handler"].rpartition(".")
                assert callable(getattr(importlib.import_module(path), name)), entry

        forbidden = (
            "sqlalchemy", "omnigent.server", "coral.db", "coral.stores",
            "coral.engine", "coral.profiles", "coral.omni.server",
        )
        loaded = sorted(
            name for name in sys.modules
            if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden)
        )
        assert not loaded, loaded
        """)

    _run_without_database_imports(tmp_path, code)

"""Tests for ``dev/lint/lint_coral_import_boundary.py``."""

from __future__ import annotations

from pathlib import Path

from dev.lint import lint_coral_import_boundary as boundary


def _write(root: Path, rel: str, code: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(code, encoding="utf-8")
    return path


def test_real_coral_tree_has_no_import_boundary_violations() -> None:
    """The checked-in coral/ package must satisfy all import tier rules."""
    coral_root = Path(__file__).resolve().parents[2] / "coral"
    assert boundary.scan_directory(coral_root) == []


def test_pure_tier_allows_stdlib_pydantic_yaml_and_pure_coral(tmp_path: Path) -> None:
    coral_root = tmp_path / "coral"
    _write(
        coral_root,
        "engine/sample.py",
        "from __future__ import annotations\n"
        "import json\n"
        "import pydantic\n"
        "import yaml\n"
        "from coral.version import CORAL_VERSION\n",
    )
    assert boundary.scan_directory(coral_root) == []


def test_pure_tier_rejects_omnigent_coral_omni_and_relative_imports(tmp_path: Path) -> None:
    coral_root = tmp_path / "coral"
    _write(coral_root, "model/bad_omnigent.py", "import omnigent.version\n")
    _write(coral_root, "engine/bad_omni.py", "from coral.omni import protocols\n")
    _write(coral_root, "validate/bad_rel.py", "from .. import omni\n")
    _write(
        coral_root,
        "evidence/ir.py",
        "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    import omnigent\n",
    )
    _write(
        coral_root,
        "rules/catalog/bad_dyn.py",
        "import importlib\nimportlib.import_module('omnigent.cli')\n",
    )

    violations = boundary.scan_directory(coral_root)
    assert len(violations) == 5
    assert any("model/bad_omnigent.py" in v for v in violations)
    assert any("engine/bad_omni.py" in v for v in violations)
    assert any("validate/bad_rel.py" in v for v in violations)
    assert any("evidence/ir.py" in v for v in violations)
    assert any("rules/catalog/bad_dyn.py" in v for v in violations)


def test_app_tier_allows_protocols_and_rejects_direct_omnigent_or_other_omni(
    tmp_path: Path,
) -> None:
    coral_root = tmp_path / "coral"
    _write(
        coral_root,
        "api/good.py",
        "import coral.omni.protocols\nfrom coral.version import CORAL_VERSION\n",
    )
    _write(coral_root, "api/bad_omnigent.py", "import omnigent.server.app\n")
    _write(coral_root, "api/bad_omni.py", "import coral.omni.server.plugin\n")

    violations = boundary.scan_directory(coral_root)
    assert len(violations) == 2
    assert any("api/bad_omnigent.py" in v for v in violations)
    assert any("api/bad_omni.py" in v for v in violations)


def test_omni_tier_restricts_underscore_imports_and_runner_host_server_imports(
    tmp_path: Path,
) -> None:
    coral_root = tmp_path / "coral"
    _write(coral_root, "omni/_upstream.py", "from omnigent.cli import _load_config\n")
    _write(coral_root, "omni/server/bad.py", "from omnigent.cli import _load_config\n")
    _write(coral_root, "omni/runner/bad.py", "import omnigent.server.app\n")
    _write(coral_root, "omni/host/bad.py", "from omnigent.server import auth\n")
    _write(coral_root, "omni/server/good.py", "from omnigent.server import auth\n")

    violations = boundary.scan_directory(coral_root)
    assert len(violations) == 3
    assert any("omni/server/bad.py" in v for v in violations)
    assert any("omni/runner/bad.py" in v for v in violations)
    assert any("omni/host/bad.py" in v for v in violations)


def test_db_tier_rejects_unallowlisted_omnigent_imports(tmp_path: Path) -> None:
    coral_root = tmp_path / "coral"
    _write(coral_root, "db/bad.py", "from omnigent.db import utils\n")

    violations = boundary.scan_directory(coral_root)
    assert len(violations) == 1
    assert "db/bad.py" in violations[0]


def test_db_tier_allows_allowlisted_omnigent_symbols_and_rejects_others(tmp_path: Path) -> None:
    coral_root = tmp_path / "coral"
    # Allowlisted public symbols in DB_OMNIGENT_ALLOWLIST
    _write(
        coral_root,
        "db/good.py",
        "from omnigent.db.db_models import DEFAULT_WORKSPACE_ID, current_workspace_id\n"
        "from omnigent.db.enum_codecs import decode_enum, encode_enum\n"
        "from omnigent.db.pagination import keyset_after\n"
        "from omnigent.db.query_context import query_name_scope\n"
        "from omnigent.db.utils import (\n"
        "    create_db_engine,\n"
        "    get_db_revision_state,\n"
        "    get_or_create_engine,\n"
        "    is_cockroachdb,\n"
        "    is_postgresql_family,\n"
        "    normalize_database_url,\n"
        "    run_write_transaction,\n"
        "    shared_read_scope,\n"
        ")\n",
    )
    # Non-allowlisted or private symbols
    _write(
        coral_root,
        "db/bad_private.py",
        "from omnigent.db.utils import _create_engine\n",
    )
    _write(
        coral_root,
        "db/bad_unallowlisted.py",
        "from omnigent.db.db_models import SqlConversation\n",
    )

    violations = boundary.scan_directory(coral_root)
    assert len(violations) == 2
    assert any("db/bad_private.py" in v for v in violations)
    assert any("db/bad_unallowlisted.py" in v for v in violations)

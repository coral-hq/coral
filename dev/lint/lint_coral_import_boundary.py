"""Enforce Coral's three-tier import boundary across ``coral/``.

Tier rules (checked via AST inspection, including ``TYPE_CHECKING`` blocks,
relative imports, and literal ``importlib.import_module(...)`` calls):

* **pure**: ``coral.__init__``, ``coral.version``, ``coral.model``,
  ``coral.validate``, ``coral.engine``, ``coral.evidence.{ir,evaluate,
  fingerprint,match,messages}``, ``coral.rules.catalog``, ``coral.workspace.ops``,
  ``coral.harness.registry``, ``coral.identity``, ``coral.runview.types``, and
  ``coral.alerts.types`` may only import stdlib, ``pydantic``, ``yaml``, and
  other pure modules.
* **omni**: ``coral.omni.**`` may import anything, except underscore-prefixed
  ``omnigent`` names/modules are restricted to ``coral/omni/_upstream.py``, and
  ``coral.omni.runner`` / ``coral.omni.host`` must never import
  ``omnigent.server``.
* **db**: ``coral.db.**`` may import stdlib, database packages (``sqlalchemy``,
  ``alembic``, ``pydantic``), pure modules, ``coral.db.**``, and explicitly
  allowlisted ``omnigent.db`` symbols.
* **root**: ``coral.cli`` and ``coral.server_plugin`` composition roots are
  exempt from the app-tier restriction on importing ``coral.omni``, while
  still never importing ``omnigent`` directly.
* **app**: all other ``coral.*`` modules may import stdlib, third-party
  packages, pure modules, ``coral.db.**``, ``coral.omni.protocols``, and other
  app modules, but never ``omnigent`` or other ``coral.omni.*`` modules.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

RULE_NAME = "coral-import-boundary"
HINT = (
    "Keep Coral's package tiers isolated: pure modules may only import stdlib, "
    "pydantic, pyyaml, and pure modules; app modules must route Omnigent access "
    "through coral.omni.protocols; and private omnigent._* symbols must go "
    "through coral/omni/_upstream.py."
)

CORAL_ROOT = Path("coral")

_PURE_EXACT_MODULES: frozenset[str] = frozenset(
    {
        "coral",
        "coral.version",
    }
)
_PURE_PREFIXES: tuple[str, ...] = (
    "coral.model",
    "coral.validate",
    "coral.engine",
    "coral.evidence.ir",
    "coral.evidence.evaluate",
    "coral.evidence.fingerprint",
    "coral.evidence.match",
    "coral.evidence.messages",
    "coral.rules.catalog",
    "coral.workspace.ops",
    "coral.harness.registry",
    "coral.identity",
    "coral.runview.types",
    "coral.alerts.types",
)
_COMPOSITION_ROOTS: frozenset[str] = frozenset({"coral.cli", "coral.server_plugin"})
_PURE_THIRD_PARTY: frozenset[str] = frozenset({"pydantic", "yaml"})
_DB_THIRD_PARTY: frozenset[str] = _PURE_THIRD_PARTY | frozenset({"sqlalchemy", "alembic"})

# Allowlisted `omnigent.db` symbols permitted inside `coral.db.**`.
DB_OMNIGENT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "omnigent.db.compression.CompressedText",
        "omnigent.db.compression.encode",
        "omnigent.db.utils.make_named_managed_session_maker",
    }
)

_STDLIB_NAMES: frozenset[str] = sys.stdlib_module_names | frozenset({"__future__"})


@dataclass(frozen=True)
class _ImportedTarget:
    line: int
    module: str
    symbol: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.module}.{self.symbol}" if self.symbol else self.module


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _module_name_for_path(path: Path, coral_root: Path) -> str:
    rel = path.relative_to(coral_root)
    parts = list(rel.parts)
    if parts[-1] == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = parts[-1].removesuffix(".py")
    return ".".join(["coral", *parts]) if parts else "coral"


def _matches_prefix(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(f"{prefix}.")


def _is_pure_module(module: str) -> bool:
    return module in _PURE_EXACT_MODULES or any(
        _matches_prefix(module, prefix) for prefix in _PURE_PREFIXES
    )


def classify_tier(module: str) -> str:
    """Return the boundary tier for a module under ``coral``."""
    if _matches_prefix(module, "coral.omni"):
        return "omni"
    if _matches_prefix(module, "coral.db"):
        return "db"
    if module in _COMPOSITION_ROOTS:
        return "root"
    if _is_pure_module(module):
        return "pure"
    return "app"


def _resolve_relative_module(
    current_module: str, is_package_init: bool, level: int, target_module: str | None
) -> str | None:
    if level == 0:
        return target_module
    parts = current_module.split(".")
    package_parts = parts if is_package_init else parts[:-1]
    steps_up = level - 1
    if steps_up > len(package_parts):
        return None
    base_parts = package_parts[: len(package_parts) - steps_up]
    if not base_parts or base_parts[0] != "coral":
        return None
    if target_module:
        return ".".join([*base_parts, target_module])
    return ".".join(base_parts)


def _extract_import_module_call(node: ast.Call) -> str | None:
    func = node.func
    is_import_module = (isinstance(func, ast.Name) and func.id == "import_module") or (
        isinstance(func, ast.Attribute) and func.attr == "import_module"
    )
    if not is_import_module:
        return None
    if (
        node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    for kw in node.keywords:
        if (
            kw.arg == "name"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            return kw.value.value
    return None


def _collect_imports(
    source: str,
    *,
    current_module: str,
    is_package_init: bool,
    display_path: str,
) -> tuple[list[_ImportedTarget], list[str]]:
    tree = ast.parse(source, filename=display_path)
    targets: list[_ImportedTarget] = []
    errors: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.append(_ImportedTarget(line=node.lineno, module=alias.name))
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_relative_module(
                current_module, is_package_init, node.level, node.module
            )
            if resolved is None:
                errors.append(
                    f"{display_path}:{node.lineno}: relative import escapes coral package"
                )
                continue
            for alias in node.names:
                symbol = None if alias.name == "*" else alias.name
                targets.append(_ImportedTarget(line=node.lineno, module=resolved, symbol=symbol))
        elif isinstance(node, ast.Call):
            lit = _extract_import_module_call(node)
            if lit is not None:
                targets.append(_ImportedTarget(line=node.lineno, module=lit))

    return targets, errors


def _has_private_omnigent_part(target: _ImportedTarget) -> bool:
    for part in target.module.split(".")[1:]:
        if part.startswith("_"):
            return True
    return target.symbol is not None and target.symbol.startswith("_")


def _check_pure(target: _ImportedTarget, display_path: str) -> str | None:
    top = target.full_name.split(".", 1)[0]
    if top in _STDLIB_NAMES or top in _PURE_THIRD_PARTY:
        return None
    if top == "coral":
        resolved = target.full_name if target.symbol else target.module
        if target.module == "coral":
            if target.symbol in {None, "CORAL_VERSION", "__version__"} or _is_pure_module(
                resolved
            ):
                return None
            return (
                f"{display_path}:{target.line}: pure module cannot import non-pure "
                f"'{target.full_name}'"
            )
        if _is_pure_module(resolved) or _is_pure_module(target.module):
            return None
        return (
            f"{display_path}:{target.line}: pure module cannot import non-pure "
            f"'{target.full_name}'"
        )
    return f"{display_path}:{target.line}: pure module cannot import '{target.full_name}'"


def _check_omni(current_module: str, target: _ImportedTarget, display_path: str) -> str | None:
    is_upstream_gateway = current_module == "coral.omni._upstream"
    if _matches_prefix(target.module, "omnigent"):
        if not is_upstream_gateway and _has_private_omnigent_part(target):
            return (
                f"{display_path}:{target.line}: underscore omnigent import '{target.full_name}' "
                "must go through coral/omni/_upstream.py"
            )
        if (
            _matches_prefix(current_module, "coral.omni.runner")
            or _matches_prefix(current_module, "coral.omni.host")
        ) and _matches_prefix(target.module, "omnigent.server"):
            return (
                f"{display_path}:{target.line}: {current_module} cannot import "
                f"'{target.full_name}'"
            )
    return None


def _check_db(target: _ImportedTarget, display_path: str) -> str | None:
    top = target.full_name.split(".", 1)[0]
    if top in _STDLIB_NAMES or top in _DB_THIRD_PARTY:
        return None
    if _matches_prefix(target.module, "coral.db"):
        return None
    if top == "coral":
        resolved = target.full_name if target.symbol else target.module
        if _is_pure_module(resolved) or _is_pure_module(target.module):
            return None
        return f"{display_path}:{target.line}: coral.db module cannot import '{target.full_name}'"
    if top == "omnigent":
        if target.full_name in DB_OMNIGENT_ALLOWLIST or target.module in DB_OMNIGENT_ALLOWLIST:
            return None
        return (
            f"{display_path}:{target.line}: coral.db module cannot import un-allowlisted "
            f"'{target.full_name}'"
        )
    return f"{display_path}:{target.line}: coral.db module cannot import '{target.full_name}'"


def _check_root(target: _ImportedTarget, display_path: str) -> str | None:
    if _matches_prefix(target.module, "omnigent"):
        return (
            f"{display_path}:{target.line}: composition root cannot import '{target.full_name}' "
            "directly (route through coral.omni)"
        )
    return None


def _check_app(target: _ImportedTarget, display_path: str) -> str | None:
    if _matches_prefix(target.module, "omnigent"):
        return (
            f"{display_path}:{target.line}: app module cannot import '{target.full_name}' "
            "(route through coral.omni)"
        )
    if _matches_prefix(target.module, "coral.omni"):
        resolved = target.full_name if target.symbol else target.module
        if _matches_prefix(target.module, "coral.omni.protocols") or _matches_prefix(
            resolved, "coral.omni.protocols"
        ):
            return None
        return (
            f"{display_path}:{target.line}: app module cannot import '{target.full_name}' "
            "(only coral.omni.protocols is permitted)"
        )
    return None


def scan_file(path: Path, *, coral_root: Path, display_path: str | None = None) -> list[str]:
    """Check one Python file under *coral_root* for tier violations."""
    shown = display_path or path.as_posix()
    current_module = _module_name_for_path(path, coral_root)
    tier = classify_tier(current_module)
    source = path.read_text(encoding="utf-8")
    targets, errors = _collect_imports(
        source,
        current_module=current_module,
        is_package_init=path.name == "__init__.py",
        display_path=shown,
    )
    for target in targets:
        err: str | None
        if tier == "pure":
            err = _check_pure(target, shown)
        elif tier == "omni":
            err = _check_omni(current_module, target, shown)
        elif tier == "db":
            err = _check_db(target, shown)
        elif tier == "root":
            err = _check_root(target, shown)
        else:
            err = _check_app(target, shown)
        if err is not None:
            errors.append(err)
    return errors


def scan_directory(coral_root: Path, *, display_prefix: str = "coral") -> list[str]:
    """Scan all ``.py`` files inside *coral_root* and return violations."""
    if not coral_root.is_dir():
        return []
    violations: list[str] = []
    for file_path in sorted(coral_root.rglob("*.py")):
        rel = file_path.relative_to(coral_root).as_posix()
        violations.extend(
            scan_file(file_path, coral_root=coral_root, display_path=f"{display_prefix}/{rel}")
        )
    return violations


def _git_coral_files(repo_root: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "ls-files", "-z", "--", "coral/"],
        cwd=repo_root,
    )
    files: list[Path] = []
    for raw in output.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8")
        if not rel.endswith(".py"):
            continue
        full = repo_root / rel
        if full.is_file():
            files.append(full)
    return files


def check(paths: Sequence[Path] | None = None) -> list[str]:
    """Run the import-boundary check across tracked ``coral/`` Python files."""
    repo_root = _repo_root()
    coral_root = repo_root / CORAL_ROOT
    if not coral_root.is_dir():
        return []
    target_files = list(paths) if paths is not None else _git_coral_files(repo_root)
    violations: list[str] = []
    for path in sorted(target_files):
        resolved = path if path.is_absolute() else (repo_root / path)
        rel = resolved.relative_to(repo_root).as_posix()
        violations.extend(scan_file(resolved, coral_root=coral_root, display_path=rel))
    return violations


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint for standalone invocation."""
    args = list(sys.argv[1:] if argv is None else argv)
    violations = check([Path(p) for p in args] if args else None)
    for item in violations:
        print(item, file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())

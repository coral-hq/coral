"""
Export the Coral API's OpenAPI document and the web's TypeScript types for it.

``uv run --no-sync python -m coral.omni.server.openapi [--check]`` writes
``coral/api/openapi.json``, built from :func:`coral_routers` (the table the plugin
mounts) on a bare app with no data directory and no authentication, and then
``web/src/workflows/api/generated/coralApi.ts`` from that document. ``--check`` fails
when either checked-in file is stale. Omnigent's own ``openapi.json`` never lists
Coral routes and is left alone.
"""

from __future__ import annotations

import argparse
import difflib
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from sqlalchemy import create_engine

from coral.api.schemas import CORAL_API_VERSION
from coral.api.sub_features import resolve_sub_features
from coral.omni.server.openapi_ts import TS_PATH, render_coral_api_types
from coral.omni.server.plugin import coral_routers
from coral.stores.workflows import SqlWorkflowDefinitionStore

SPEC_PATH = Path(__file__).resolve().parents[2] / "api" / "openapi.json"
REGENERATE = "just coral openapi"
_MAX_DIFF_LINES = 60


def coral_openapi() -> dict[str, Any]:
    """The OpenAPI document of every Coral route."""
    # The routes never read the store while the document is built.
    engine = create_engine("sqlite://")
    try:
        routers = coral_routers(
            sub_features=resolve_sub_features(None),
            definitions=SqlWorkflowDefinitionStore(engine),
            auth_provider=None,
        )
        app = FastAPI(title="Coral API", version=CORAL_API_VERSION)
        for router, prefix, tags in routers:
            app.include_router(router, prefix=prefix, tags=[*tags])
        return app.openapi()
    finally:
        engine.dispose()


def render_openapi(spec: dict[str, Any]) -> str:
    """``spec`` as the checked-in file holds it: sorted, indented, ending in a newline."""
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def export(spec_path: Path = SPEC_PATH, ts_path: Path = TS_PATH, *, check: bool = False) -> int:
    """
    Write the document to ``spec_path`` and its types to ``ts_path``, or with ``check``
    only compare them.

    :returns: 0, or 1 when ``check`` finds a file stale (a diff goes to stderr).
    """
    spec = coral_openapi()
    stale = 0
    for path, rendered in (
        (spec_path, render_openapi(spec)),
        (ts_path, render_coral_api_types(spec)),
    ):
        if not check:
            path.write_text(rendered, encoding="utf-8")
            continue
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current == rendered:
            continue
        stale = 1
        diff = difflib.unified_diff(
            current.splitlines(), rendered.splitlines(), str(path), "generated", lineterm=""
        )
        print(f"{path} is stale; run `{REGENERATE}`.", file=sys.stderr)
        print("\n".join(list(diff)[:_MAX_DIFF_LINES]), file=sys.stderr)
    return stale


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the Coral API document and its types.")
    parser.add_argument("--check", action="store_true", help="fail when a file is stale")
    return export(check=parser.parse_args(argv).check)


if __name__ == "__main__":
    raise SystemExit(main())

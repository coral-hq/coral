"""
Export the Coral API's OpenAPI document and the web's TypeScript types for it.

``uv run --no-sync python -m coral.omni.server.openapi [--check]`` writes
``coral/api/openapi.json``, built from :func:`coral_routers` (the table the plugin
mounts) on a bare app with no data directory and no authentication, and then
``web/src/workflows/api/generated/coralApi.ts`` from that document. ``--check`` fails
when either checked-in file is stale. Omnigent's own ``openapi.json`` never lists
Coral routes and is left alone.

The run stream's frames are not response models, so their schemas are added here, as
FastAPI writes components; one that FastAPI already wrote must be the same.
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
from fastapi.encoders import jsonable_encoder
from fastapi.openapi.models import OpenAPI
from pydantic import TypeAdapter
from sqlalchemy import create_engine

from coral.api.schemas import CORAL_API_VERSION
from coral.api.sub_features import resolve_sub_features
from coral.omni.server.openapi_ts import TS_PATH, render_coral_api_types
from coral.omni.server.plugin import coral_routers
from coral.runview.types import RunStreamFrame
from coral.stores.workflows import SqlWorkflowDefinitionStore

SPEC_PATH = Path(__file__).resolve().parents[2] / "api" / "openapi.json"
REGENERATE = "just coral openapi"
_MAX_DIFF_LINES = 60
EVENT_STREAM = "text/event-stream"
_REF_TEMPLATE = "#/components/schemas/{model}"


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
        spec = app.openapi()
    finally:
        engine.dispose()
    _event_streams_only(spec)
    add_schemas(spec, stream_frame_schemas())
    return spec


def _event_streams_only(spec: dict[str, Any]) -> None:
    """A success that streams events answers nothing else: drop FastAPI's JSON entry."""
    for item in spec["paths"].values():
        for operation in item.values():
            for status, response in operation.get("responses", {}).items():
                content = response.get("content", {})
                if status.startswith("2") and EVENT_STREAM in content:
                    content.pop("application/json", None)


def stream_frame_schemas() -> dict[str, Any]:
    """``RunStreamFrame`` and the schemas it uses, as FastAPI writes components."""
    generated = TypeAdapter(RunStreamFrame).json_schema(
        ref_template=_REF_TEMPLATE, mode="serialization"
    )
    schemas = {**generated.pop("$defs"), "RunStreamFrame": generated}
    # FastAPI drops null members, such as a ``default`` of None, when it writes a document.
    document = OpenAPI.model_validate(
        {
            "openapi": "3.1.0",
            "info": {"title": "", "version": ""},
            "components": {"schemas": schemas},
        }
    )
    return jsonable_encoder(document, by_alias=True, exclude_none=True)["components"]["schemas"]


def add_schemas(spec: dict[str, Any], schemas: dict[str, Any]) -> None:
    """
    Add ``schemas`` to the document's components.

    :raises ValueError: when one has the name of a different schema already there.
    """
    components = spec.setdefault("components", {}).setdefault("schemas", {})
    for name, schema in schemas.items():
        if name in components and components[name] != schema:
            raise ValueError(f"The added schema {name} differs from the document's own")
        components[name] = schema


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

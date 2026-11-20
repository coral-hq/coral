"""The TypeScript emitter: each schema form it lays out, operations, and what it refuses."""

from __future__ import annotations

from typing import Any

import pytest

from coral.omni.server.openapi_ts import UnsupportedSchema, render_coral_api_types

KINDS = [f"kind_number_{index}" for index in range(8)]


def _ref(name: str) -> dict[str, str]:
    return {"$ref": f"#/components/schemas/{name}"}


def _spec(**schemas: dict[str, Any]) -> dict[str, Any]:
    """A document with ``schemas`` and one operation: POST a ``Body``, answer a ``Reply``."""
    operation = {
        "operationId": "coral_send_thing",
        "description": "Send one thing.",
        "parameters": [
            {"in": "path", "name": "thing_id", "required": True, "schema": {"type": "string"}},
            {"in": "query", "name": "limit", "required": False, "schema": {"type": "integer"}},
        ],
        "requestBody": {"content": {"application/json": {"schema": _ref("Body")}}},
        "responses": {
            "200": {"content": {"application/json": {"schema": _ref("Reply")}}},
            "404": {"content": {"application/json": {"schema": _ref("CoralErrorResponse")}}},
            "422": {"content": {"application/json": {"schema": _ref("CoralErrorResponse")}}},
        },
    }
    return {
        "paths": {"/v1/coral/things/{thing_id}": {"post": operation}},
        "components": {"schemas": schemas},
    }


BODY = {
    "type": "object",
    "description": "What a client sends.",
    "properties": {
        "note": {"type": "string", "default": ""},
        "tags": {"$ref": "#/components/schemas/Tags"},
    },
    "required": ["tags"],
}


def test_each_schema_form_has_its_typescript_layout() -> None:
    reply = {
        "type": "object",
        "description": "First line.\n\nSecond paragraph.",
        "properties": {
            "count": {"type": "integer", "default": 0},
            "details": {
                "anyOf": [{"type": "null"}, {"type": "object", "additionalProperties": True}]
            },
            "kind": {"enum": KINDS, "type": "string"},
            "labels": {"type": "array", "items": {"enum": ["a", "b"], "type": "string"}},
            "ok": {"const": True},
            "parent": {"anyOf": [_ref("Reply"), {"type": "null"}]},
            "scores": {"type": "object", "additionalProperties": {"type": "number"}},
            "weird-name": {"description": "Any value.", "title": "Weird"},
        },
    }

    rendered = render_coral_api_types(
        _spec(
            Body=BODY,
            Empty={"type": "object", "properties": {}, "additionalProperties": False},
            Reply=reply,
            Tags={"type": "array", "items": {"type": "string"}},
        )
    )

    assert rendered == "\n".join(
        [
            "// Generated from coral/api/openapi.json by coral/omni/server/openapi_ts.py; "
            "do not edit.",
            "// Regenerate with `just coral openapi`.",
            "",
            "/** What a client sends. */",
            "export interface Body {",
            "  note?: string;",
            "  tags: Tags;",
            "}",
            "",
            "export type Empty = Record<string, never>;",
            "",
            "/**",
            " * First line.",
            " *",
            " * Second paragraph.",
            " */",
            "export interface Reply {",
            "  count: number;",
            "  details: Record<string, unknown> | null;",
            "  kind:",
            *(f'    | "{kind}"' for kind in KINDS[:-1]),
            f'    | "{KINDS[-1]}";',
            '  labels: ("a" | "b")[];',
            "  ok: true;",
            "  parent: Reply | null;",
            "  scores: Record<string, number>;",
            "  /** Any value. */",
            '  "weird-name": unknown;',
            "}",
            "",
            "export type Tags = string[];",
            "",
            "/**",
            " * Every Coral operation by its operationId.",
            " * Each status in `errors` answers a `CoralErrorResponse` body.",
            " */",
            "export interface CoralOperations {",
            "  /**",
            "   * POST /v1/coral/things/{thing_id}",
            "   *",
            "   * Send one thing.",
            "   */",
            "  coral_send_thing: {",
            '    method: "POST";',
            '    path: "/v1/coral/things/{thing_id}";',
            "    params: {",
            "      thing_id: string;",
            "    };",
            "    query: {",
            "      limit?: number;",
            "    };",
            "    body: Body;",
            "    status: 200;",
            "    response: Reply;",
            "    errors: 404 | 422;",
            "  };",
            "}",
            "",
        ]
    )


def test_an_answer_with_no_content_is_null() -> None:
    spec = _spec(Body=BODY, Reply=BODY, Tags={"type": "string"})
    responses = spec["paths"]["/v1/coral/things/{thing_id}"]["post"]["responses"]
    responses["204"] = {"description": "No Content"}
    del responses["200"]

    rendered = render_coral_api_types(spec)

    assert "    status: 204;\n    response: null;\n" in rendered


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(
            {
                "type": "object",
                "properties": {
                    "inner": {"type": "object", "properties": {"a": {"type": "string"}}}
                },
            },
            id="nested-object",
        ),
        pytest.param({"$ref": "https://example.com/schema.json"}, id="remote-reference"),
        pytest.param(
            {"type": "object", "properties": {"x" * 100: {"type": "string"}}}, id="over-width"
        ),
    ],
)
def test_a_form_it_cannot_lay_out_is_refused(schema: dict[str, Any]) -> None:
    with pytest.raises(UnsupportedSchema):
        render_coral_api_types(_spec(Body=BODY, Reply=schema, Tags={"type": "string"}))

"""
TypeScript types for the web, generated from the Coral OpenAPI document.

:func:`render_coral_api_types` turns ``coral/api/openapi.json`` into one module of
``export interface`` and ``export type`` declarations: one per component schema, and
``CoralOperations``, each operation's method, path, parameters, body, response and
refusal statuses by ``operationId``. An operation answering server-sent events has no
JSON response; its ``events`` are the type of each event's data.

A schema no request body uses is response-only. The server sends every field of a
response (no Coral route excludes unset, default or null fields), so none of its
fields is optional. The output is already in the web's Prettier style (100 columns,
two-space indent); a construct it cannot lay out that way raises instead of writing a
file Prettier would rewrite.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

TS_PATH = Path(__file__).resolve().parents[3] / "web/src/workflows/api/generated/coralApi.ts"
_HEADER = (
    "// Generated from coral/api/openapi.json by coral/omni/server/openapi_ts.py; do not edit.\n"
    "// Regenerate with `just coral openapi`.\n"
)
_PRINT_WIDTH = 100
_INDENT = "  "
_REF_PREFIX = "#/components/schemas/"
_IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_OPERATIONS_DOC = (
    "Every Coral operation by its operationId.\n"
    "Each status in `errors` answers a `CoralErrorResponse` body."
)
_PRIMITIVES = {"string": "string", "integer": "number", "number": "number", "boolean": "boolean"}
# Keywords that describe a schema without constraining it.
_ANNOTATIONS = frozenset({"title", "description", "default", "examples"})
_EVENT_STREAM = "text/event-stream"
_EVENTS_DOC = "Server-sent events: each event's `data` is one of these, or `[DONE]` at the end."


class UnsupportedSchema(ValueError):
    """The document uses a schema form the emitter has no TypeScript layout for."""


def _literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float | str) or value is None:
        return json.dumps(value)
    raise UnsupportedSchema(f"literal {value!r}")


def _key(name: str) -> str:
    return name if _IDENTIFIER.fullmatch(name) else json.dumps(name)


def _members(schema: Mapping[str, Any]) -> list[str]:
    """The union members ``schema`` stands for, each a single-line TypeScript type."""
    if "$ref" in schema:
        ref = schema["$ref"]
        if not ref.startswith(_REF_PREFIX):
            raise UnsupportedSchema(f"reference {ref!r}")
        return [ref.removeprefix(_REF_PREFIX)]
    if "const" in schema:
        return [_literal(schema["const"])]
    if "enum" in schema:
        return [_literal(value) for value in schema["enum"]]
    if "anyOf" in schema or "oneOf" in schema:
        found: list[str] = []
        for member in schema.get("anyOf", schema.get("oneOf", ())):
            found.extend(_members(member))
        unique = list(dict.fromkeys(found))
        # ``null`` last, as people write it.
        return [member for member in unique if member != "null"] + (
            ["null"] if "null" in unique else []
        )
    kind = schema.get("type")
    if kind is None and _ANNOTATIONS.issuperset(schema):
        # Any JSON value, as Pydantic's ``JsonValue`` is.
        return ["unknown"]
    if kind == "null":
        return ["null"]
    if kind in _PRIMITIVES:
        return [_PRIMITIVES[kind]]
    if kind == "array" and "prefixItems" not in schema:
        items = _members(schema.get("items", {}))
        item = items[0] if len(items) == 1 else f"({' | '.join(items)})"
        return [f"{item}[]"]
    if kind == "object" and not schema.get("properties"):
        extra = schema.get("additionalProperties", True)
        if extra is False:
            return ["Record<string, never>"]
        value = "unknown" if extra is True else " | ".join(_members(extra))
        return [f"Record<string, {value}>"]
    raise UnsupportedSchema(f"schema {json.dumps(schema, sort_keys=True)[:120]}")


def _comment(text: str | None, indent: str) -> list[str]:
    if not text:
        return []
    lines = text.replace("*/", "*\\/").strip().splitlines()
    if len(lines) == 1:
        return [f"{indent}/** {lines[0].strip()} */"]
    body = [f"{indent} * {line.rstrip()}".rstrip() for line in lines]
    return [f"{indent}/**", *body, f"{indent} */"]


def _member_line(indent: str, head: str, members: list[str]) -> list[str]:
    """``head`` (``name:`` or ``name?:``) typed as ``members``, laid out as Prettier does."""
    single = f"{indent}{head} {' | '.join(members)};"
    if len(single) <= _PRINT_WIDTH or len(members) == 1:
        if len(single) > _PRINT_WIDTH:
            raise UnsupportedSchema(f"line over {_PRINT_WIDTH} columns: {single.strip()}")
        return [single]
    hanging = f"{indent}{_INDENT}{' | '.join(members)};"
    if head.endswith(":") and len(hanging) <= _PRINT_WIDTH:
        # A property's union that fits on the next line stays on one line there.
        return [f"{indent}{head}", hanging]
    broken = [f"{indent}{head}"] + [f"{indent}{_INDENT}| {member}" for member in members]
    broken[-1] += ";"
    if any(len(line) > _PRINT_WIDTH for line in broken):
        raise UnsupportedSchema(f"union member over {_PRINT_WIDTH} columns in {head}")
    return broken


def _properties(schema: Mapping[str, Any], indent: str, *, sent: bool = False) -> list[str]:
    """One line per property; with ``sent`` (a response's schema), every one is present."""
    required = set(schema["properties"] if sent else schema.get("required", ()))
    lines: list[str] = []
    for name, field in sorted(schema.get("properties", {}).items()):
        lines += _comment(field.get("description"), indent)
        head = f"{_key(name)}{'' if name in required else '?'}:"
        lines += _member_line(indent, head, _members(field))
    return lines


def _block(head: str, lines: Iterable[str], indent: str) -> list[str]:
    """``head {`` then ``lines`` then the closing brace, one property per line."""
    return [
        f"{indent}{head} {{",
        *lines,
        f"{indent}}}" + ("" if head.startswith("export") else ";"),
    ]


def _refs(value: object) -> Iterable[str]:
    if isinstance(value, Mapping):
        ref = value.get("$ref")
        if isinstance(ref, str) and ref.startswith(_REF_PREFIX):
            yield ref.removeprefix(_REF_PREFIX)
        for child in value.values():
            yield from _refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _refs(child)


def _request_schemas(spec: Mapping[str, Any]) -> set[str]:
    """Every component a request body uses, directly or through other components."""
    schemas = spec.get("components", {}).get("schemas", {})
    pending = [
        name
        for item in spec["paths"].values()
        for method in _METHODS
        if method in item
        for name in _refs(item[method].get("requestBody", {}))
    ]
    found: set[str] = set()
    while pending:
        name = pending.pop()
        if name not in found:
            found.add(name)
            pending.extend(_refs(schemas.get(name, {})))
    return found


def _schema_declaration(name: str, schema: Mapping[str, Any], *, sent: bool) -> list[str]:
    lines = _comment(schema.get("description"), "")
    if schema.get("type") == "object" and schema.get("properties"):
        body = _properties(schema, _INDENT, sent=sent)
        return lines + _block(f"export interface {name}", body, "")
    return lines + _member_line("", f"export type {name} =", _members(schema))


def _parameters(operation: Mapping[str, Any], where: str, indent: str) -> list[str]:
    found = [param for param in operation.get("parameters", ()) if param["in"] == where]
    if not found:
        return []
    fields = {param["name"]: param["schema"] for param in found}
    required = [param["name"] for param in found if param.get("required")]
    body = _properties({"properties": fields, "required": required}, indent + _INDENT)
    return _block("params:" if where == "path" else "query:", body, indent)


def _json_schema(holder: Mapping[str, Any]) -> Mapping[str, Any] | None:
    content = holder.get("content", {})
    return content.get("application/json", {}).get("schema") if content else None


def _operation(method: str, path: str, operation: Mapping[str, Any]) -> list[str]:
    indent = _INDENT * 2
    about = operation.get("description")
    lines = _comment(f"{method.upper()} {path}" + (f"\n\n{about}" if about else ""), _INDENT)
    body: list[str] = [
        f'{indent}method: "{method.upper()}";',
        f"{indent}path: {json.dumps(path)};",
    ]
    body += _parameters(operation, "path", indent)
    body += _parameters(operation, "query", indent)
    request = operation.get("requestBody")
    if request is not None:
        schema = _json_schema(request)
        if schema is None:
            raise UnsupportedSchema(f"{operation['operationId']}: a body that is not JSON")
        body += _member_line(indent, "body:", _members(schema))
    statuses = sorted(operation["responses"])
    successes = [status for status in statuses if status.startswith("2")]
    if successes:
        # A route with several success statuses answers any of their bodies.
        members: list[str] = []
        events: list[str] = []
        for status in successes:
            content = operation["responses"][status].get("content", {})
            if _EVENT_STREAM in content:
                events.extend(_members(content[_EVENT_STREAM]["schema"]))
                continue
            schema = _json_schema(operation["responses"][status])
            members.extend(["null"] if schema is None else _members(schema))
        unique = list(dict.fromkeys(members))
        response = [member for member in unique if member != "null"]
        response += ["null"] if "null" in unique else []
        body += _member_line(indent, "status:", successes)
        # A stream of events answers no JSON body.
        body += _member_line(indent, "response:", response or ["never"])
        if events:
            body += _comment(_EVENTS_DOC, indent)
            body += _member_line(indent, "events:", list(dict.fromkeys(events)))
    else:
        # A route not served yet answers only refusals.
        body += [f"{indent}status: never;", f"{indent}response: never;"]
    # A 304 has no body and is not a refusal.
    errors = [status for status in statuses if status.startswith(("4", "5"))]
    if errors:
        body += _member_line(indent, "errors:", errors)
    return lines + _block(f"{_key(operation['operationId'])}:", body, _INDENT)


def render_coral_api_types(spec: Mapping[str, Any]) -> str:
    """The generated module for ``spec``, the parsed Coral OpenAPI document."""
    requests = _request_schemas(spec)
    sections: list[list[str]] = []
    for name, schema in sorted(spec.get("components", {}).get("schemas", {}).items()):
        sections.append(_schema_declaration(name, schema, sent=name not in requests))
    operations: list[str] = []
    for path, item in sorted(spec["paths"].items()):
        for method in _METHODS:
            if method in item:
                operations += _operation(method, path, item[method])
    sections.append(
        _comment(_OPERATIONS_DOC, "") + _block("export interface CoralOperations", operations, "")
    )
    return _HEADER + "".join("\n" + "\n".join(section) + "\n" for section in sections)


__all__ = ["TS_PATH", "UnsupportedSchema", "render_coral_api_types"]

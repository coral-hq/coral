"""Apply a stored run-view patch: RFC 6902 ``add``, ``remove`` and ``replace`` by position.

The engine diffs arrays by index (``coral/engine/projection.py``), so a patch applies
only to the exact view it was made from. ``remove`` may carry ``"value": null``.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence

from pydantic import JsonValue, TypeAdapter

from coral.engine.types import JsonPatch

# At most 18 digits: no view has that many items, and ``int()`` stays far below its limit.
_ARRAY_INDEX = re.compile(r"0|[1-9][0-9]{0,17}")
_BAD_ESCAPE = re.compile(r"~(?![01])")
_STORED_PATCH: TypeAdapter[tuple[JsonPatch, ...]] = TypeAdapter(tuple[JsonPatch, ...])


class ViewPatchError(ValueError):
    """A patch operation the view cannot take: a bad pointer or a missing target."""


def stored_view_patch(text: str | None) -> tuple[JsonPatch, ...]:
    """The operations of a run-log row's ``view_patch``; a row without one has none.

    :raises pydantic.ValidationError: for text that is not a JSON patch.
    """
    return () if text is None else _STORED_PATCH.validate_json(text)


def apply_view_patch(
    view: Mapping[str, JsonValue], patch: Sequence[JsonPatch]
) -> dict[str, JsonValue]:
    """A new view with ``patch`` applied in order; ``view`` and the patch are left unchanged.

    Only the objects and arrays an operation writes into are copied, so the result shares
    every untouched part with ``view``: change neither in place.

    :raises ViewPatchError: for an operation whose pointer the view cannot take, or a
        result that is not a JSON object.
    """
    document: JsonValue = dict(view)
    # The containers this call copied, kept alive so their ids stay theirs.
    copies: dict[int, JsonValue] = {id(document): document}
    for operation in patch:
        document = _apply(document, operation, copies)
    if not isinstance(document, dict):
        raise ViewPatchError("a patched view must be a JSON object")
    return document


def _apply(document: JsonValue, operation: JsonPatch, copies: dict[int, JsonValue]) -> JsonValue:
    tokens = _tokens(operation.path)
    value = copy.deepcopy(operation.value)
    if not tokens:
        if operation.op == "remove":
            raise ViewPatchError("cannot remove the whole view")
        return value
    document = _own(document, copies)
    parent = _writable(document, tokens[:-1], operation.path, copies)
    last = tokens[-1]
    if isinstance(parent, dict):
        if operation.op == "add":
            parent[last] = value
        elif last not in parent:
            raise ViewPatchError(f"{operation.path}: no such member")
        elif operation.op == "remove":
            del parent[last]
        else:
            parent[last] = value
    elif isinstance(parent, list):
        if operation.op == "add":
            index = len(parent) if last == "-" else _index(last, len(parent), operation.path)
            parent.insert(index, value)
        else:
            index = _index(last, len(parent) - 1, operation.path)
            if operation.op == "remove":
                del parent[index]
            else:
                parent[index] = value
    else:
        raise ViewPatchError(f"{operation.path}: the parent is not an object or an array")
    return document


def _tokens(path: str) -> list[str]:
    """The reference tokens of a JSON pointer (RFC 6901); the empty pointer is the root."""
    if path == "":
        return []
    if not path.startswith("/"):
        raise ViewPatchError(f"{path}: a pointer starts with '/'")
    if _BAD_ESCAPE.search(path):
        raise ViewPatchError(f"{path}: '~' must be followed by '0' or '1'")
    tokens = path[1:].split("/")
    return [token.replace("~1", "/").replace("~0", "~") for token in tokens]


def _writable(
    document: JsonValue, tokens: Sequence[str], path: str, copies: dict[int, JsonValue]
) -> JsonValue:
    """The container ``tokens`` names, with it and every container above it copied once."""
    node = document
    for token in tokens:
        if isinstance(node, dict):
            if token not in node:
                raise ViewPatchError(f"{path}: no such member")
            child = node[token] = _own(node[token], copies)
        elif isinstance(node, list):
            index = _index(token, len(node) - 1, path)
            child = node[index] = _own(node[index], copies)
        else:
            raise ViewPatchError(f"{path}: the parent is not an object or an array")
        node = child
    return node


def _own(node: JsonValue, copies: dict[int, JsonValue]) -> JsonValue:
    """``node`` itself when this call copied it or it is a scalar; else a shallow copy."""
    if not isinstance(node, dict | list) or id(node) in copies:
        return node
    copied = copy.copy(node)
    copies[id(copied)] = copied
    return copied


def _index(token: str, highest: int, path: str) -> int:
    if not _ARRAY_INDEX.fullmatch(token) or int(token) > highest:
        raise ViewPatchError(f"{path}: no such array index")
    return int(token)


__all__ = ["ViewPatchError", "apply_view_patch", "stored_view_patch"]

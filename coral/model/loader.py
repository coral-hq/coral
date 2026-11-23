"""Load workflow YAML into an authoring model with a source map.

The pure tier cannot import ``omnigent``, so the YAML 1.2 bool handling mirrors
``omnigent.spec.parser._ConfigYamlLoader``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import yaml
from pydantic import ValidationError

from coral.model.authoring import Workflow
from coral.model.sourcemap import SourceMap, SourceRange, child_path

MAX_DOCUMENT_BYTES = 256 * 1024
MAX_DEPTH = 32

_BOOL_TAG = "tag:yaml.org,2002:bool"
_STR_TAG = "tag:yaml.org,2002:str"
_MERGE_TAG = "tag:yaml.org,2002:merge"
_INT_TAG = "tag:yaml.org,2002:int"
_FLOAT_TAG = "tag:yaml.org,2002:float"
# No field needs a longer integer; a longer one, in any YAML 1.1 form, is refused unread.
MAX_INT_CHARS = 64
_UNREADABLE_VALUE = (
    "invalid YAML: a value cannot be read, such as an impossible date or a number "
    "with too many digits; quote it to keep it as text"
)
# JSON's number form: no hex, octal, binary, base-60, underscores, leading zeros or .inf.
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?")
# What plain JSON data resolves to: no timestamps, sets, binary or ordered maps.
_JSON_TAGS = frozenset(
    {
        _STR_TAG,
        _BOOL_TAG,
        _INT_TAG,
        _FLOAT_TAG,
        "tag:yaml.org,2002:null",
        "tag:yaml.org,2002:seq",
        "tag:yaml.org,2002:map",
    }
)
_YAML_1_2_BOOL_RE = re.compile(r"^(?:true|True|TRUE|false|False|FALSE)$")


class _CoralYamlLoader(yaml.SafeLoader):
    """SafeLoader that keeps ``on``/``off``/``yes``/``no`` as strings.

    YAML 1.1 resolves them to booleans; only ``true``/``false`` stay booleans here.
    """


# Copy the resolver dict before mutating: it is inherited from SafeLoader by
# reference, so in-place edits would strip SafeLoader's bool resolver process-wide.
_CoralYamlLoader.yaml_implicit_resolvers = {
    key: value[:] for key, value in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
for _first_char in list(_CoralYamlLoader.yaml_implicit_resolvers.keys()):
    _CoralYamlLoader.yaml_implicit_resolvers[_first_char] = [
        (tag, regexp)
        for tag, regexp in _CoralYamlLoader.yaml_implicit_resolvers[_first_char]
        if tag != _BOOL_TAG
    ]
_CoralYamlLoader.add_implicit_resolver(  # type: ignore[no-untyped-call]
    _BOOL_TAG,
    _YAML_1_2_BOOL_RE,
    list("tTfF"),
)


@dataclass(frozen=True)
class LoadIssue:
    yaml_path: str
    range: SourceRange | None
    message: str


@dataclass(frozen=True)
class LoadError:
    """A document that could not be loaded; ``issues`` lists every schema error."""

    code: str
    yaml_path: str
    range: SourceRange | None
    message: str
    issues: tuple[LoadIssue, ...] = ()


@dataclass(frozen=True)
class Loaded:
    workflow: Workflow
    source_map: SourceMap
    text: str


def _range_of(node: yaml.Node) -> SourceRange:
    start, end = node.start_mark, node.end_mark
    return SourceRange(start.line + 1, start.column + 1, end.line + 1, end.column + 1)


def _range_of_mark(mark: yaml.Mark) -> SourceRange:
    return SourceRange(mark.line + 1, mark.column + 1, mark.line + 1, mark.column + 1)


def _scan_events(text: str) -> LoadError | None:
    """Reject aliases and over-deep nesting before composing (avoids recursion limits)."""
    depth = 0
    try:
        for event in yaml.parse(text, Loader=_CoralYamlLoader):
            if isinstance(event, yaml.AliasEvent):
                return LoadError(
                    "alias",
                    "",
                    _range_of_mark(event.start_mark),
                    f"YAML alias '*{event.anchor}' is not allowed; repeat the value instead",
                )
            if isinstance(event, yaml.MappingStartEvent | yaml.SequenceStartEvent):
                depth += 1
                if depth > MAX_DEPTH:
                    return LoadError(
                        "too_deep",
                        "",
                        _range_of_mark(event.start_mark),
                        f"document nesting exceeds {MAX_DEPTH} levels; flatten the structure",
                    )
            elif isinstance(event, yaml.MappingEndEvent | yaml.SequenceEndEvent):
                depth -= 1
    except yaml.YAMLError as error:
        return _yaml_error(error)
    return None


def _yaml_error(error: yaml.YAMLError) -> LoadError:
    mark = getattr(error, "problem_mark", None)
    problem = getattr(error, "problem", None) or str(error)
    return LoadError(
        "invalid_yaml",
        "",
        _range_of_mark(mark) if mark is not None else None,
        f"invalid YAML: {problem}",
    )


def _walk(
    node: yaml.Node,
    path: str,
    ranges: dict[str, SourceRange],
    allowed_tags: frozenset[str] | None = None,
) -> LoadError | None:
    """Record ranges and reject duplicate, merge and non-string mapping keys, and long integers.

    With ``allowed_tags``, also reject a value of any other YAML type, and a number not
    written as JSON writes it.
    """
    ranges[path] = _range_of(node)
    if node.tag == _INT_TAG and len(str(node.value)) > MAX_INT_CHARS:
        return LoadError("invalid_yaml", path, _range_of(node), _UNREADABLE_VALUE)
    if allowed_tags is not None and node.tag not in allowed_tags:
        return LoadError(
            "unsupported_type",
            path,
            _range_of(node),
            "only strings, numbers, booleans, null, lists and mappings are allowed; "
            "quote the value to keep it as text",
        )
    if (
        allowed_tags is not None
        and node.tag in {_INT_TAG, _FLOAT_TAG}
        and _JSON_NUMBER.fullmatch(str(node.value)) is None
    ):
        return LoadError(
            "unsupported_type",
            path,
            _range_of(node),
            "write numbers as plain decimals, such as 3 or 2.5; "
            "quote the value to keep it as text",
        )
    if isinstance(node, yaml.MappingNode):
        seen: set[str] = set()
        for key_node, value_node in node.value:
            if key_node.tag == _MERGE_TAG:
                return LoadError(
                    "merge_key",
                    path,
                    _range_of(key_node),
                    "YAML merge keys ('<<') are not allowed; write the keys out explicitly",
                )
            if not isinstance(key_node, yaml.ScalarNode) or key_node.tag != _STR_TAG:
                return LoadError(
                    "non_string_key",
                    path,
                    _range_of(key_node),
                    "mapping keys must be strings; quote the key",
                )
            key = key_node.value
            key_path = child_path(path, key)
            if key in seen:
                return LoadError(
                    "duplicate_key",
                    key_path,
                    _range_of(key_node),
                    f"duplicate key '{key}'; each key may appear once in a mapping",
                )
            seen.add(key)
            failure = _walk(value_node, key_path, ranges, allowed_tags)
            if failure is not None:
                return failure
    elif isinstance(node, yaml.SequenceNode):
        for index, item in enumerate(node.value):
            failure = _walk(item, child_path(path, index), ranges, allowed_tags)
            if failure is not None:
                return failure
    return None


def _location_path(location: tuple[int | str, ...]) -> str:
    """Convert a Pydantic error location into a ``yaml_path``."""
    path = ""
    for position, part in enumerate(location):
        # Skip the discriminated-union tag segment (e.g. ``nodes[1].step.goal``).
        if (
            isinstance(part, str)
            and position >= 2
            and isinstance(location[position - 1], int)
            and location[position - 2] == "nodes"
        ):
            continue
        path = child_path(path, part)
    return path


def _schema_error(error: ValidationError, source_map: SourceMap) -> LoadError:
    issues = []
    for detail in error.errors():
        path = _location_path(detail["loc"])
        message = detail["msg"].removeprefix("Value error, ")
        issues.append(LoadIssue(path, source_map.lookup(path), message))
    first = issues[0]
    suffix = f" (and {len(issues) - 1} more)" if len(issues) > 1 else ""
    return LoadError(
        "invalid_document",
        first.yaml_path,
        first.range,
        f"{first.yaml_path or 'document'}: {first.message}{suffix}",
        tuple(issues),
    )


def _compose(text: str) -> yaml.Node | LoadError | None:
    """Compose one document after the text, size, alias and depth guards."""
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError:
        return LoadError(
            "invalid_text",
            "",
            None,
            "the document holds an unpaired surrogate, which is not valid Unicode text",
        )
    if len(encoded) > MAX_DOCUMENT_BYTES:
        return LoadError(
            "oversized",
            "",
            None,
            f"document exceeds {MAX_DOCUMENT_BYTES // 1024} KiB; split or shorten the workflow",
        )
    scan_failure = _scan_events(text)
    if scan_failure is not None:
        return scan_failure
    try:
        return yaml.compose(text, Loader=_CoralYamlLoader)
    except yaml.YAMLError as error:
        return _yaml_error(error)


def _construct(root: yaml.Node) -> object | LoadError:
    try:
        return _CoralYamlLoader("").construct_object(root, deep=True)
    except yaml.YAMLError as error:
        return _yaml_error(error)
    except ValueError:
        # An impossible date, for example; the value is not quoted.
        return LoadError("invalid_yaml", "", None, _UNREADABLE_VALUE)


def load_yaml_data(text: str) -> object | LoadError:
    """Parse one YAML document under the workflow loader's guards and return its plain data.

    The same size cap, alias and depth scan, and key checks as ``load``, and only
    JSON-compatible values; an empty document is ``None``.
    """
    root = _compose(text)
    if root is None or isinstance(root, LoadError):
        return root
    walk_failure = _walk(root, "", {}, _JSON_TAGS)
    if walk_failure is not None:
        return walk_failure
    return _construct(root)


def load(text: str) -> Loaded | LoadError:
    """Parse workflow YAML, enforcing structural guards and the authoring schema."""
    root = _compose(text)
    if isinstance(root, LoadError):
        return root
    if not isinstance(root, yaml.MappingNode):
        return LoadError(
            "invalid_document",
            "",
            _range_of(root) if root is not None else None,
            "a workflow document must be a YAML mapping with id, name, nodes and arrows",
        )
    ranges: dict[str, SourceRange] = {}
    walk_failure = _walk(root, "", ranges)
    if walk_failure is not None:
        return walk_failure
    document = _construct(root)
    if isinstance(document, LoadError):
        return document
    source_map = SourceMap(ranges)
    try:
        workflow = Workflow.model_validate(document)
    except ValidationError as error:
        return _schema_error(error, source_map)
    return Loaded(workflow=workflow, source_map=source_map, text=text)

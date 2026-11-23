"""Coral's built-in workflow templates, shipped as package data.

A template is ``<stem>.yaml`` beside its saved Simulate cases, ``<stem>.sim.yaml``. Only the
stems :data:`BUILTIN_TEMPLATES` lists are templates; other files in this package are not.
A template is found by comparing its workflow id, never by a file name built from a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable

from coral.engine.simcase import SimCase, load_cases
from coral.model import CompiledGraph, Loaded
from coral.model.ids import validate_workflow_id
from coral.validate.pipeline import check_text

# File stems, in gallery order.
BUILTIN_TEMPLATES: tuple[str, ...] = ("implement_review_loop",)
TEMPLATE_SUFFIX = ".yaml"
CASES_SUFFIX = ".sim.yaml"


class TemplateError(RuntimeError):
    """A packaged template that does not load, validate, or carry its saved cases."""


@dataclass(frozen=True)
class BuiltinTemplate:
    """A built-in template; ``id`` is its workflow's id, e.g. ``implement-review-loop``."""

    id: str
    name: str
    description: str
    yaml_text: str
    loaded: Loaded
    graph: CompiledGraph
    cases: tuple[SimCase, ...]


def builtin_templates() -> tuple[BuiltinTemplate, ...]:
    """Read, validate and return every registered template, in gallery order.

    :raises TemplateError: when a template is broken or two share a workflow id.
    """
    templates = tuple(_load_template(stem) for stem in BUILTIN_TEMPLATES)
    ids = [template.id for template in templates]
    if len(set(ids)) != len(ids):
        raise TemplateError(f"built-in templates need unique workflow ids, got {ids}")
    return templates


def builtin_template(template_id: str) -> BuiltinTemplate | None:
    """Return the built-in template whose workflow id equals ``template_id``, else ``None``."""
    return next((item for item in builtin_templates() if item.id == template_id), None)


def with_workflow_id(template: BuiltinTemplate, workflow_id: str) -> str:
    """Return the template's text with its top-level ``id`` value replaced, every other byte kept.

    :raises ValueError: when ``workflow_id`` is not a valid workflow id.
    :raises TemplateError: when the template's id is not written as a one-line plain scalar.
    """
    validate_workflow_id(workflow_id)
    span = template.loaded.source_map.ranges.get("id")
    lines = template.yaml_text.split("\n")
    if span is None or span.start_line != span.end_line or span.start_line > len(lines):
        raise TemplateError(f"built-in template {template.id!r} needs its id on one line")
    index = span.start_line - 1
    line = lines[index]
    start, end = span.start_column - 1, span.end_column - 1
    # A quoted or block scalar's span holds more than the id itself.
    if line[start:end] != template.id:
        raise TemplateError(f"built-in template {template.id!r} needs a plain, unquoted id")
    lines[index] = line[:start] + workflow_id + line[end:]
    return "\n".join(lines)


def _package_files() -> Traversable:
    return resources.files(__name__)


def _load_template(stem: str) -> BuiltinTemplate:
    package = _package_files()
    template_file = package.joinpath(f"{stem}{TEMPLATE_SUFFIX}")
    cases_file = package.joinpath(f"{stem}{CASES_SUFFIX}")
    for needed in (template_file, cases_file):
        if not needed.is_file():
            raise TemplateError(f"built-in template {stem!r} needs the file {needed.name}")
    try:
        text = template_file.read_text("utf-8")
    except (OSError, ValueError) as error:
        raise TemplateError(f"built-in template {stem!r} cannot be read: {error}") from error
    checked = check_text(text)
    loaded, graph, report = checked.loaded, checked.graph, checked.report
    if loaded is None or graph is None or report is None:
        failure = checked.load_error
        detail = f"{failure.code}: {failure.message}" if failure is not None else "no graph"
        raise TemplateError(f"built-in template {stem!r} does not load: {detail}")
    if not report.runnable:
        first = report.errors[0]
        raise TemplateError(
            f"built-in template {stem!r} does not validate: {first.rule}: {first.message}"
        )
    description = loaded.workflow.description
    if description is None or not description.strip():
        raise TemplateError(f"built-in template {stem!r} needs a description")
    try:
        cases = load_cases(cases_file.read_text("utf-8")).cases
    except (OSError, ValueError) as error:
        raise TemplateError(
            f"built-in template {stem!r} has unreadable saved cases: {error}"
        ) from error
    return BuiltinTemplate(
        id=graph.workflow_id,
        name=graph.name,
        description=description,
        yaml_text=text,
        loaded=loaded,
        graph=graph,
        cases=cases,
    )

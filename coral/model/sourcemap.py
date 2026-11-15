"""Map ``yaml_path`` anchors (e.g. ``nodes[1].goal``) to source ranges."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field

# Last path segment: ``.key`` or ``[index]``.
_LAST_SEGMENT = re.compile(r"(?:\.[^.\[\]]+|\[\d+\])$")


@dataclass(frozen=True)
class SourceRange:
    """1-based inclusive start, exclusive end positions in the YAML text."""

    start_line: int
    start_column: int
    end_line: int
    end_column: int


def child_path(parent: str, key: str | int) -> str:
    """Path of a mapping key or sequence index under ``parent``."""
    if isinstance(key, int):
        return f"{parent}[{key}]"
    return f"{parent}.{key}" if parent else key


def node_path(index: int) -> str:
    return f"nodes[{index}]"


def arrow_path(index: int) -> str:
    return f"arrows[{index}]"


@dataclass(frozen=True)
class SourceMap:
    """Ranges for every mapping value, sequence item and scalar in a document."""

    ranges: Mapping[str, SourceRange] = field(default_factory=dict)

    def lookup(self, yaml_path: str) -> SourceRange | None:
        """Range for the path, or for its nearest ancestor when it is absent."""
        path = yaml_path
        while True:
            found = self.ranges.get(path)
            if found is not None:
                return found
            trimmed = _LAST_SEGMENT.sub("", path)
            if trimmed == path:
                return self.ranges.get("")
            path = trimmed

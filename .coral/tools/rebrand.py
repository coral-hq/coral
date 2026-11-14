"""Coral's re-runnable brand transform (seam S95).

Rewrites the product name "Omnigent" to "Coral" in user-visible text that
Coral inherits from Omnigent's Python code: prose string literals (messages,
prompts, option help) and the docstrings click shows as command help. The
`omnigent` package, imports, identifiers, comments, wire contracts (header
names, paths, single-word values), credits and statements about upstream
installs or documentation stay unchanged.

Upstream syncs apply it to each upstream snapshot before merging, so the
transformed lines never conflict (docs/coral/UPSTREAM_SYNC.md).

Usage, from the repository root:
  python .coral/tools/rebrand.py apply [PATH ...]   rewrite files in place
  python .coral/tools/rebrand.py check [PATH ...]   exit 1 if apply would change a file
  python .coral/tools/rebrand.py report [PATH ...]  list the "Omnigent" strings left and why

Without PATH it covers the tracked Python files under SCOPE.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SEAM = "S95"
ANCHOR = (
    f'# CORAL({SEAM}): user-visible "Omnigent" text changed to "Coral" by .coral/tools/rebrand.py'
)
ANCHOR_PREFIX = f"# CORAL({SEAM}):"

SCOPE = ("omnigent", "tests")
# tests/frontends/sdk/ tests the sdks/ packages, which the transform leaves alone.
EXCLUDED_PREFIXES = ("tests/coral/", "tests/frontends/sdk/")
# Tests that pin text from non-Python sources this transform leaves alone.
EXCLUDED_FILES = frozenset(
    {
        "tests/harnesses/pi_native/test_pi_native_extension.py",  # the Pi JS extension
        "tests/scripts/test_ci_usage.py",  # GitHub Action YAML
        "tests/scripts/test_install_oss.py",  # scripts/install_oss.sh
        "tests/test_uninstall_oss.py",  # scripts/uninstall_oss.sh
    }
)

# The product name as a word. Not part of an identifier, header name, path or
# file name: "X-Omnigent-Session-Id", "/Omnigent", "Omnigent.app" stay.
PRODUCT_WORD = re.compile(r"(?<![\w\-./@#$])Omnigent(?!\w|-[A-Z]|\.[a-z])")

COMPOUND = re.compile(r"(?<![\w\-./@#$])Omnigent-[a-z]")

# The CLI command in help text, rewritten only where click shows it as help.
COMMAND_WORD = re.compile(
    r"(?<![\w\-./@#$~])(?:omnigent|omni)(?=[ \t]+(?:--?[a-z]|[a-z][a-z-]*\b))"
)

# A literal containing any of these speaks about upstream as a fact (install
# commands, documentation, telemetry, credits) and keeps "Omnigent".
UPSTREAM_FACTS = (
    "omnigent.ai",
    "omnigent-ai",
    "omnigent-telemetry",
    "install omnigent",
    "pip install",
    "uv tool install",
    "Copyright",
    "Databricks, Inc",
    "CORAL(",
)

# Text that code outside SCOPE writes or matches exactly. Changing only the
# Python copy would break the other side, so both keep "Omnigent".
SHARED_TEXT = (
    "Omnigent user configuration",  # sdks/ui terminal config header
    "Omnigent Automation",  # web/src default project for scheduled tasks
    "Omnigent automation sent this message",  # web/src/lib/systemMessage.ts hides this note
    "Omnigent captured a pane snapshot",  # web/src/components/blocks/StatusBlocks.tsx
    "starts one Omnigent session",  # web/src/components/scheduled/triggerTemplates.ts
)

# Credits to upstream ("Built on Omnigent", "Powered by Omnigent").
CREDIT = re.compile(r"(?i)\b(?:built on|powered by|based on|fork of|derived from) Omnigent\b")

# Text of the upstream shell installer (scripts/install_oss.sh), including
# the profile markers it writes and Omnigent's uninstaller reads back.
UPSTREAM_INSTALLER = re.compile(r"\bOmnigent install(?:er|ed)\b")

# "an Omnigent" becomes "a Coral".
ARTICLE = re.compile(r"\b([Aa])n(\s+)(?=Omnigent(?!\w|-[A-Z]|\.[a-z]))")

CLICK_DECORATOR_NAMES = frozenset({"command", "group"})


@dataclass(frozen=True)
class Kept:
    """A literal that still says "Omnigent" after the transform."""

    path: str
    line: int
    reason: str
    text: str


def is_prose(text: str) -> bool:
    """Prose has whitespace or a compound like "Omnigent-owned"; other single
    words are values such as names or keys."""
    return any(character.isspace() for character in text) or bool(COMPOUND.search(text))


def keeps_omnigent(text: str) -> bool:
    """Whether a literal states an upstream fact or holds text shared outside SCOPE."""
    if any(marker in text for marker in (*UPSTREAM_FACTS, *SHARED_TEXT)):
        return True
    return bool(CREDIT.search(text) or UPSTREAM_INSTALLER.search(text))


def rewrite_product(text: str) -> str:
    return PRODUCT_WORD.sub("Coral", ARTICLE.sub(r"\1\2", text))


def rewrite_help(text: str) -> str:
    return COMMAND_WORD.sub("coral", rewrite_product(text))


def click_help_docstrings(source: str) -> set[tuple[int, int]]:
    """Start positions of docstrings that click renders as command help."""
    positions: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        if not any(_is_click_decorator(decorator) for decorator in node.decorator_list):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            positions.add((first.value.lineno, first.value.col_offset))
    return positions


def _is_click_decorator(decorator: ast.expr) -> bool:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Attribute):
        return target.attr in CLICK_DECORATOR_NAMES
    return isinstance(target, ast.Name) and target.id in CLICK_DECORATOR_NAMES


def help_keyword_strings(source: str) -> set[tuple[int, int]]:
    """Start positions of string pieces passed as ``help=`` (click options)."""
    positions: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        for keyword in node.keywords:
            if keyword.arg in {"help", "short_help", "epilog"}:
                for piece in ast.walk(keyword.value):
                    if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                        positions.add((piece.lineno, piece.col_offset))
    return positions


def docstring_positions(source: str) -> set[tuple[int, int]]:
    positions: set[tuple[int, int]] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                positions.add((first.value.lineno, first.value.col_offset))
    return positions


def _string_groups(tokens: list[tokenize.TokenInfo]) -> list[list[tuple[tuple[int, int], int]]]:
    """Group string tokens into literals, implicit concatenations included.

    Each group is a list of (start, token index) pieces. An f-string
    contributes its literal middles; its expressions do not.
    """
    groups: list[list[tuple[tuple[int, int], int]]] = []
    depth = 0
    joinable = False
    skipped = (tokenize.NL, tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT)
    for index, token in enumerate(tokens):
        if depth == 0:
            if token.type in (tokenize.STRING, tokenize.FSTRING_START):
                if not joinable:
                    groups.append([])
                if token.type == tokenize.STRING:
                    groups[-1].append((token.start, index))
                    joinable = True
                else:
                    depth = 1
                    groups[-1].append((token.start, -1))
            elif token.type not in skipped:
                joinable = False
            continue
        if token.type == tokenize.FSTRING_START:
            depth += 1
        elif token.type == tokenize.FSTRING_END:
            depth -= 1
            joinable = depth == 0
        elif token.type == tokenize.FSTRING_MIDDLE:
            groups[-1].append((token.start, index))
    return groups


def transform_source(source: str, path: str = "<string>") -> tuple[str, list[Kept]]:
    """Return the rebranded source and the literals that keep "Omnigent"."""
    if "mnigent" not in source and "omni " not in source:
        return source, []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        docstrings = docstring_positions(source)
        click_help = click_help_docstrings(source) | help_keyword_strings(source)
    except (SyntaxError, tokenize.TokenError):
        return source, []

    offsets = [0]
    for line in _lines(source):
        offsets.append(offsets[-1] + len(line))

    def absolute(position: tuple[int, int]) -> int:
        return offsets[position[0] - 1] + position[1]

    edits: list[tuple[int, int, str]] = []
    kept: list[Kept] = []
    for group in _string_groups(tokens):
        group_start = group[0][0]
        spans = []
        for _start, index in group:
            if index < 0:
                continue
            begin = absolute(tokens[index].start)
            # Middles report unescaped text, so slice up to the next token.
            end = absolute(
                tokens[index + 1].start
                if tokens[index].type == tokenize.FSTRING_MIDDLE
                else tokens[index].end
            )
            spans.append((begin, end))
        text = "".join(source[begin:end] for begin, end in spans)
        is_help = group_start in click_help
        if group_start in docstrings and not is_help:
            continue
        has_product = bool(PRODUCT_WORD.search(text))
        has_command = is_help and bool(COMMAND_WORD.search(text))
        line = group_start[0]
        if not has_product and not has_command:
            if "Omnigent" in text:
                kept.append(Kept(path, line, "identifier or compound", text))
            continue
        if keeps_omnigent(text):
            kept.append(Kept(path, line, "upstream fact or shared text", text))
            continue
        if not is_help and not is_prose(text):
            kept.append(Kept(path, line, "single-word value", text))
            continue
        rewrite = rewrite_help if is_help else rewrite_product
        for begin, end in spans:
            replacement = rewrite(source[begin:end])
            if replacement != source[begin:end]:
                edits.append((begin, end, replacement))

    if not edits:
        return source, kept
    pieces: list[str] = []
    cursor = 0
    for begin, end, replacement in edits:
        pieces.append(source[cursor:begin])
        pieces.append(replacement)
        cursor = end
    pieces.append(source[cursor:])
    result = "".join(pieces)
    verify_only_strings_changed(source, result, path)
    return add_anchor(result), kept


def verify_only_strings_changed(before: str, after: str, path: str) -> None:
    """Fail unless the two sources differ only by the intended string rewrites."""
    old_constants: list[str] = []
    new_constants: list[str] = []

    def masked(source: str, sink: list[str]) -> str:
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                sink.append(node.value)
                node.value = ""
        return ast.dump(tree)

    if masked(before, old_constants) != masked(after, new_constants):
        raise ValueError(f"{path}: rebrand changed code outside string literals")
    for old, new in zip(old_constants, new_constants, strict=True):
        if new not in (old, rewrite_product(old), rewrite_help(old)):
            raise ValueError(f"{path}: unexpected rewrite {old[:80]!r} -> {new[:80]!r}")


def _lines(source: str) -> list[str]:
    """Split lines exactly as tokenize reads them (on "\n" only)."""
    return io.StringIO(source).readlines()


def add_anchor(source: str) -> str:
    """Put the seam anchor at the top, after any shebang or encoding line."""
    if ANCHOR_PREFIX in source:
        return source
    lines = _lines(source)
    index = 0
    while (
        index < len(lines)
        and index < 2
        and (lines[index].startswith("#!") or re.match(r"^[ \t\f]*#.*coding[:=]", lines[index]))
    ):
        index += 1
    lines.insert(index, ANCHOR + "\n")
    return "".join(lines)


def tracked_files(paths: Iterable[str]) -> list[str]:
    roots = list(paths) or list(SCOPE)
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--", *roots],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split("\0")
    return sorted(
        path
        for path in listed
        if path.endswith(".py")
        and not path.startswith(EXCLUDED_PREFIXES)
        and path not in EXCLUDED_FILES
        and Path(path).is_file()
    )


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"apply", "check", "report"}:
        print(__doc__, file=sys.stderr)
        return 2
    command, paths = argv[0], argv[1:]
    changed: list[str] = []
    all_kept: list[Kept] = []
    for path in tracked_files(paths):
        with open(path, encoding="utf-8", newline="") as handle:
            source = handle.read()
        result, kept = transform_source(source, path)
        all_kept.extend(kept)
        if result != source:
            changed.append(path)
            if command == "apply":
                with open(path, "w", encoding="utf-8", newline="") as handle:
                    handle.write(result)
    if command == "report":
        for item in all_kept:
            print(f"{item.path}:{item.line}: {item.reason}: {item.text[:120]!r}")
        print(
            f"{len(all_kept)} literals keep 'Omnigent'; {len(changed)} files would change",
            file=sys.stderr,
        )
        return 0
    if command == "apply" and changed:
        # Shorter strings can let implicit concatenations join; format the
        # rewritten files the way the ruff-format hook would.
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--quiet", "--force-exclude", *changed],
            check=True,
        )
    for path in changed:
        print(path)
    if command == "check" and changed:
        print(
            f"{len(changed)} files are not rebranded; run: python .coral/tools/rebrand.py apply",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

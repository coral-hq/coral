"""Tests for Coral's re-runnable brand transform, ``.coral/tools/rebrand.py``."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / ".coral" / "tools" / "rebrand.py"


def _load_rebrand() -> ModuleType:
    spec = importlib.util.spec_from_file_location("coral_rebrand", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


rebrand = _load_rebrand()


def transform(source: str) -> str:
    return rebrand.transform_source(source, "example.py")[0]


def body(source: str) -> str:
    """The transformed source without the seam anchor line."""
    return "".join(
        line
        for line in transform(source).splitlines(keepends=True)
        if rebrand.ANCHOR_PREFIX not in line
    )


def test_rewrites_prose_strings_and_adds_one_anchor() -> None:
    source = 'MESSAGE = "Could not reach the Omnigent server."\nOTHER = "Omnigent is ready"\n'
    result = transform(source)
    assert result.splitlines()[0] == rebrand.ANCHOR
    assert result.count(rebrand.ANCHOR_PREFIX) == 1
    assert 'MESSAGE = "Could not reach the Coral server."' in result
    assert 'OTHER = "Coral is ready"' in result


def test_anchor_goes_after_shebang_and_encoding_lines() -> None:
    source = '#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nprint("Omnigent says hi")\n'
    lines = transform(source).splitlines()
    assert lines[:3] == ["#!/usr/bin/env python3", "# -*- coding: utf-8 -*-", rebrand.ANCHOR]


def test_untouched_source_gets_no_anchor() -> None:
    source = 'HEADER = "X-Omnigent-Session-Id"\n'
    assert transform(source) == source


@pytest.mark.parametrize(
    "literal",
    [
        '"Omnigent"',  # single-word value such as a name or key
        '"X-Omnigent-Launch-Id header missing"',  # header name inside prose
        '"open /Applications/Omnigent.app now"',  # file name
        '"OmnigentClient failed to start"',  # identifier
        '"See the Omnigent docs at https://omnigent.ai/docs"',  # upstream documentation
        '"Run pip install omnigent to get Omnigent"',  # upstream install command
        '"Coral is built on Omnigent"',  # credit
        '"Powered by Omnigent"',  # credit
        '"# >>> Omnigent installer >>>"',  # upstream installer marker
        '"# Omnigent user configuration"',  # written by sdks/, outside the scope
        '"Omnigent Automation"',  # named by the web UI, outside the scope
        '"Note: an Omnigent automation sent this message."',  # matched by the web UI
    ],
)
def test_keeps_values_contracts_and_upstream_facts(literal: str) -> None:
    source = f"VALUE = {literal}\n"
    assert transform(source) == source


def test_comments_and_ordinary_docstrings_stay() -> None:
    source = (
        '"""Module docstring about Omnigent internals."""\n'
        "# Omnigent comment\n"
        "def helper():\n"
        '    """Helper docstring: run omnigent stop in Omnigent."""\n'
        "    return 1\n"
    )
    assert transform(source) == source


def test_click_help_names_coral_but_keeps_the_omnigent_commands() -> None:
    source = (
        "@cli.command()\n"
        '@click.option("--server", help="Remote Omnigent server URL.")\n'
        "def usage():\n"
        '    """Show your Omnigent usage.\n'
        "\n"
        "    Examples:\n"
        "      omnigent usage --json\n"
        "      omni usage\n"
        '    """\n'
    )
    result = body(source)
    assert '"""Show your Coral usage.' in result
    assert "      omnigent usage --json\n" in result
    assert "      omni usage\n" in result
    assert 'help="Remote Coral server URL."' in result


def test_runtime_messages_keep_the_command_name() -> None:
    source = 'HINT = "Run `omnigent login` to sign in to Omnigent."\n'
    assert 'HINT = "Run `omnigent login` to sign in to Coral."' in body(source)


def test_article_follows_the_new_name() -> None:
    source = 'A = "Start an Omnigent session"\nB = "An Omnigent agent replied"\n'
    result = body(source)
    assert 'A = "Start a Coral session"' in result
    assert 'B = "A Coral agent replied"' in result


def test_hyphenated_compound_in_a_single_word_is_prose() -> None:
    assert 'FLAG = "Coral-owned"' in body('FLAG = "Omnigent-owned"\n')


def test_fstring_keeps_escaped_braces_and_expressions() -> None:
    source = 'MESSAGE = f"{{literal}} Omnigent {name!r:>{width}} done {{"\n'
    assert body(source) == 'MESSAGE = f"{{literal}} Coral {name!r:>{width}} done {{"\n'


def test_implicit_concatenation_is_judged_as_one_literal() -> None:
    source = 'MESSAGE = (\n    "Install Omnigent with "\n    "pip install omnigent"\n)\n'
    assert transform(source) == source


def test_transform_is_idempotent() -> None:
    source = (
        'A = "Omnigent server"\n'
        "@cli.command()\n"
        "def run():\n"
        '    """Run omnigent run in Omnigent."""\n'
    )
    once = transform(source)
    assert transform(once) == once


def test_unparseable_source_is_left_alone() -> None:
    source = 'MESSAGE = "Omnigent server"\nif True\n'
    assert transform(source) == source


def test_verification_rejects_changes_outside_string_literals() -> None:
    with pytest.raises(ValueError, match="outside string literals"):
        rebrand.verify_only_strings_changed(
            'x = "Omnigent server"\n', 'y = "Coral server"\n', "example.py"
        )


def test_verification_rejects_unexpected_rewrites() -> None:
    with pytest.raises(ValueError, match="unexpected rewrite"):
        rebrand.verify_only_strings_changed(
            'x = "Omnigent server"\n', 'x = "Other server"\n', "example.py"
        )


def test_form_feeds_and_crlf_lines_keep_their_positions() -> None:
    source = 'A = "x\x0cy Omnigent server"\r\nB = "Omnigent   next"\r\n'
    assert body(source) == 'A = "x\x0cy Coral server"\r\nB = "Coral   next"\r\n'

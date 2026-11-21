"""Run-view patch cases for the web's applier to match, decided by ``apply_view_patch``.

Each case is a ``view`` and a ``patch`` with what the Python applier makes of them: its
``result``, or ``error: true`` where it refuses. ``client_error: true`` marks a case the web
must refuse although Python takes it: a ``__proto__``, ``constructor`` or ``prototype``
token, or a pointer past 16 tokens or 1,024 characters, which no ``RunView`` path is. Each
rule case declares its verdict, and the build fails when Python disagrees. The rules come
first, then every non-empty patch of the run-view contract's live recording, on the view
the stream sent it to.

Regenerate the checked-in file: ``uv run --no-sync python -m
tests.coral.runview.view_patch_contract --write`` (the web Prettier hook then formats it;
the test compares parsed JSON).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import JsonValue, ValidationError

from coral.runview.patch import ViewPatchError, apply_view_patch, stored_view_patch
from tests.coral.api import run_view_contract
from tests.coral.api._stream_client import DONE, StreamClient
from tests.coral.api.run_view_contract import SentEvent, wire_event, write_or_check

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "web/src/workflows/fixtures/viewPatch.contract.json"
)
MODULE = "tests.coral.runview.view_patch_contract"
# The web's caps on a pointer; Python has none, and no run-view path comes near them.
MAX_POINTER_TOKENS = 16
MAX_POINTER_CHARS = 1_024

VIEW: dict[str, JsonValue] = {
    "status": "running",
    "items": ["a", "b"],
    "nested": {"a/b": 1, "m~n": 2},
    "none": None,
    "rows": [{"id": "r1", "slots": [{"status": "working"}]}],
}

Verdict = Literal["result", "error", "client_error"]
Patch = list[dict[str, JsonValue]]
Case = tuple[str, dict[str, JsonValue], Patch, Verdict]


def _op(op: str, path: str, value: JsonValue = None) -> dict[str, JsonValue]:
    return {"op": op, "path": path, "value": value}


def _one(
    name: str,
    verdict: Verdict,
    op: str,
    path: str,
    value: JsonValue = None,
    view: dict[str, JsonValue] | None = None,
) -> Case:
    """A one-operation case on :data:`VIEW`, or on ``view``."""
    return (name, VIEW if view is None else view, [_op(op, path, value)], verdict)


def _nested(depth: int) -> dict[str, JsonValue]:
    """Objects ``depth`` deep under the key ``k``: ``{"k": {"k": ... {}}}``."""
    view: dict[str, JsonValue] = {}
    for _ in range(depth):
        view = {"k": view}
    return view


def _rule_cases() -> list[Case]:
    """The applier's rules, each with what it must come to."""
    at_cap, past_cap = MAX_POINTER_TOKENS - 1, MAX_POINTER_TOKENS
    long_key = "x" * (MAX_POINTER_CHARS - 1)
    return [
        # The root; the result must be an object only once every operation is applied.
        _one("root replace", "result", "replace", "", {"status": "done"}),
        _one("root add", "result", "add", "", {"status": "done"}),
        _one("root remove", "error", "remove", ""),
        _one("root replace by an array", "error", "replace", "", ["a"]),
        _one("root add of a scalar", "error", "add", "", 1),
        (
            "an array root replaced by an object",
            VIEW,
            [_op("replace", "", ["a"]), _op("replace", "", {"k": 1})],
            "result",
        ),
        # Members.
        _one("add a new member", "result", "add", "/added", 1),
        ("add without a value", VIEW, [{"op": "add", "path": "/added"}], "result"),
        _one("add over a member", "result", "add", "/status", "paused"),
        _one("replace a member", "result", "replace", "/status", "paused"),
        _one("replace a member with null", "result", "replace", "/status", None),
        _one("remove a member", "result", "remove", "/none"),
        ("remove without a value", VIEW, [{"op": "remove", "path": "/none"}], "result"),
        _one("replace a missing member", "error", "replace", "/missing", 1),
        _one("remove a missing member", "error", "remove", "/missing"),
        _one("a missing intermediate member", "error", "add", "/missing/x", 1),
        _one("an inherited member", "error", "replace", "/toString", 1, view={}),
        _one("an own member named toString", "result", "replace", "/toString", 2, {"toString": 1}),
        _one("a value with a __proto__ key", "result", "add", "/x", {"__proto__": {"a": 1}}),
        # Arrays.
        _one("array add at 0", "result", "add", "/items/0", "z"),
        _one("array add at its length", "result", "add", "/items/2", "z"),
        _one("array add at -", "result", "add", "/items/-", "z"),
        _one("array add past its length", "error", "add", "/items/3", "z"),
        _one("array replace at its last index", "result", "replace", "/items/1", "z"),
        _one("array replace at its length", "error", "replace", "/items/2", "z"),
        _one("array replace at -", "error", "replace", "/items/-", "z"),
        _one("array remove at 0", "result", "remove", "/items/0"),
        _one("array remove at its length", "error", "remove", "/items/2"),
        _one("- as an intermediate token", "error", "add", "/rows/-/id", "r2"),
        _one("an intermediate index past the end", "error", "add", "/rows/1/id", "r2"),
        _one("a leading zero index", "error", "replace", "/items/01", "z"),
        _one("a negative index", "error", "replace", "/items/-1", "z"),
        _one("an exponent index", "error", "replace", "/items/1e3", "z"),
        _one("an 18-digit index past the end", "error", "replace", "/items/" + "9" * 18, "z"),
        _one("a 19-digit index", "error", "replace", "/items/" + "1" * 19, "z"),
        _one("a member token on an array", "error", "replace", "/items/first", "z"),
        _one("length on an array", "error", "replace", "/items/length", 0),
        _one("a nested path through arrays", "result", "replace", "/rows/0/slots/0/status", "x"),
        _one("add into a nested array", "result", "add", "/rows/0/slots/-", {"status": "x"}),
        # Escapes, pointers and parents.
        _one("~1 unescapes to /", "result", "replace", "/nested/a~1b", 3),
        _one("~0 unescapes to ~", "result", "replace", "/nested/m~0n", 3),
        _one("~01 unescapes to ~1", "result", "replace", "/~01", 2, view={"~1": 1}),
        _one("a bad ~2 escape", "error", "add", "/nested/m~2n", 3),
        _one("a pointer without /", "error", "add", "status", "paused"),
        _one("an empty token", "result", "add", "/nested/", 3),
        _one("a scalar parent", "error", "add", "/status/x", 1),
        _one("an index into a string", "error", "add", "/status/0", "x"),
        _one("a null parent", "error", "add", "/none/x", 1),
        # Several operations apply in order, and one refused refuses the patch.
        (
            "operations in order",
            VIEW,
            [
                _op("add", "/items/-", "c"),
                _op("replace", "/items/2", "d"),
                _op("remove", "/items/0"),
            ],
            "result",
        ),
        (
            "a later operation refused",
            VIEW,
            [_op("replace", "/status", "paused"), _op("remove", "/missing")],
            "error",
        ),
        ("an empty patch", VIEW, [], "result"),
        # Only add, remove and replace.
        *(
            (f"the {op} op", VIEW, [{"op": op, "from": "/status", "path": "/x"}], "error")
            for op in ("move", "copy", "test", "unknown")
        ),
        # A plain view has no prototype member to walk through.
        _one("add through __proto__", "error", "add", "/__proto__/polluted", True, view={}),
        _one("add through constructor", "error", "add", "/constructor/prototype/x", 1, view={}),
        # Prototype tokens Python takes as ordinary keys.
        _one("add /__proto__", "client_error", "add", "/__proto__", {"polluted": True}, view={}),
        _one("add /constructor", "client_error", "add", "/constructor", 1, view={}),
        _one("add /prototype", "client_error", "add", "/prototype", 1, view={}),
        _one(
            "replace an own __proto__",
            "client_error",
            "replace",
            "/__proto__",
            2,
            {"__proto__": 1},
        ),
        _one(
            "remove an own constructor",
            "client_error",
            "remove",
            "/constructor",
            None,
            {"constructor": 1},
        ),
        _one(
            "add through an own __proto__",
            "client_error",
            "add",
            "/__proto__/x",
            1,
            {"__proto__": {}},
        ),
        _one(
            "add through an own constructor",
            "client_error",
            "add",
            "/constructor/prototype/x",
            1,
            view={"constructor": {"prototype": {}}},
        ),
        # The web's pointer caps: at the cap both take it, past it only the web refuses.
        _one(
            f"a pointer of {at_cap + 1} tokens",
            "result",
            "add",
            "/k" * at_cap + "/x",
            1,
            _nested(at_cap),
        ),
        _one(
            f"a pointer of {past_cap + 1} tokens",
            "client_error",
            "add",
            "/k" * past_cap + "/x",
            1,
            _nested(past_cap),
        ),
        _one(
            f"a pointer of {MAX_POINTER_CHARS} characters",
            "result",
            "add",
            f"/{long_key}",
            1,
            view={},
        ),
        _one(
            f"a pointer of {MAX_POINTER_CHARS + 1} characters",
            "client_error",
            "add",
            f"/{long_key}x",
            1,
            view={},
        ),
    ]


def _entry_cases(live: Sequence[SentEvent]) -> list[Case]:
    """Every non-empty patch of the live recording, on the view the stream sent it to."""
    client = StreamClient()
    cases: list[Case] = []
    for event in live:
        if event["data"] == DONE:
            break
        assert event["data"] is not None
        data = json.loads(event["data"])
        if data["type"] == "entry" and data["patch"]:
            assert client.view is not None
            name = f"live entry {data['seq']} ({data['kind']})"
            cases.append((name, client.view, data["patch"], "result"))
        client.take(wire_event(event))
    return cases


def _case(name: str, view: dict[str, JsonValue], patch: Patch, verdict: Verdict) -> dict[str, Any]:
    """The case with Python's result or refusal, which must be ``verdict``."""
    case: dict[str, Any] = {"name": name, "view": view, "patch": patch}
    try:
        case["result"] = apply_view_patch(view, stored_view_patch(json.dumps(patch)))
    except (ViewPatchError, ValidationError):
        case["error"] = True
    # A client-only refusal is one Python takes.
    assert ("error" in case) == (verdict == "error"), (name, case)
    if verdict == "client_error":
        case["client_error"] = True
    return case


def build_contract(live: Sequence[SentEvent] | None = None) -> dict[str, Any]:
    """
    The contract: ``cases``, each ``{name, view, patch}`` with ``result`` or ``error``, and
    ``client_error`` on the cases only the web refuses.

    :param live: The run-view contract's live recording; recorded afresh when not given.
    """
    recorded = run_view_contract.build_contract()["live"] if live is None else live
    cases = [_case(*case) for case in [*_rule_cases(), *_entry_cases(recorded)]]
    names = [case["name"] for case in cases]
    assert len(set(names)) == len(names), names
    # As the wire carries it.
    return json.loads(json.dumps({"cases": cases}))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the run-view patch contract fixture.")
    parser.add_argument("--write", action="store_true", help="rewrite the checked-in file")
    args = parser.parse_args(argv)
    return write_or_check(build_contract(), CONTRACT_PATH, write=args.write, module=MODULE)


if __name__ == "__main__":
    sys.exit(main())

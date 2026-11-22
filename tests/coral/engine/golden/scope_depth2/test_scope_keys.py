"""ENG-08 step 1: K2 scope keys at item_path depth 2 (no repeat behaviour yet).

A 3 × 2 nested path freezes the activation_id / effect_key / gate-visit id
shapes before fan-out lands, so M2 can freeze K2 against these fixtures.
"""

from __future__ import annotations

from coral.engine.types import activation_id, effect_key
from coral.gates.ids import gate_visit_id

# Outer repeat items a,b,c × inner items 0,1 — stable ids frozen at fan-out later.
_OUTER = ("a", "b", "c")
_INNER = ("0", "1")
_NODE = "review"
_RUN = "run_pr_review_1"


def test_activation_ids_nest_item_paths_to_depth_two() -> None:
    ids = [activation_id(_NODE, (outer, inner), ()) for outer in _OUTER for inner in _INNER]
    assert ids == [
        "review|a/0|",
        "review|a/1|",
        "review|b/0|",
        "review|b/1|",
        "review|c/0|",
        "review|c/1|",
    ]
    assert len(set(ids)) == 6


def test_effect_keys_include_run_seq_kind_and_activation_subject() -> None:
    subject = activation_id(_NODE, ("b", "1"), ())
    key = effect_key(_RUN, 12, "structure.start_item", subject)
    assert key == f"{_RUN}:12:structure.start_item:{subject}"


def test_gate_visit_ids_are_stable_hex_of_run_and_token() -> None:
    token = activation_id(_NODE, ("a", "0"), ()) + ":gate"
    first = gate_visit_id(_RUN, token)
    second = gate_visit_id(_RUN, token)
    assert first == second
    assert len(first) == 32
    assert int(first, 16) >= 0
    other = gate_visit_id(_RUN, activation_id(_NODE, ("a", "1"), ()) + ":gate")
    assert other != first

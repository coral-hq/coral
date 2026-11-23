"""The built-in template's simulations the web's Simulate panel tests replay.

Each case runs one script on the "Implement with review loop" template through
``coral.api.workflows.simulated``, the function ``POST /v1/coral/workflows:simulate``
answers with. The file holds the template's compiled graph once and each case's
``simulation``; the engine uses one fixed clock, so the output is stable.

Regenerate the checked-in file: ``uv run --no-sync python -m tests.coral.api.simulate_contract
--write`` (the web Prettier hook then formats it; the test compares parsed JSON).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from coral.api.schemas import SimulatedResult
from coral.api.workflows import simulated
from coral.engine.simulate import SimScript
from coral.templates import builtin_template
from coral.validate import ValidateContext
from tests.coral.api.run_view_contract import write_or_check

CONTRACT_PATH = (
    Path(__file__).resolve().parents[3] / "web/src/workflows/fixtures/reviewLoopSimulations.json"
)
MODULE = "tests.coral.api.simulate_contract"
TEMPLATE_ID = "implement-review-loop"
# Each case's script inputs, as the panel builds them one answer at a time.
SCRIPTS: dict[str, list[dict[str, Any]]] = {
    "needs_review": [],
    "needs_gate": [{"node_id": "review", "kind": "label", "values": ["approved"]}],
    "approved": [
        {"node_id": "review", "kind": "label", "values": ["approved"]},
        {"node_id": "approve_change", "kind": "gate", "values": ["approve"]},
    ],
    "changes_to_limit": [
        {"node_id": "review", "kind": "label", "values": ["changes_requested"] * 3},
        {"node_id": "approve_change", "kind": "gate", "values": ["approve"]},
    ],
}


def template_text() -> str:
    template = builtin_template(TEMPLATE_ID)
    assert template is not None, TEMPLATE_ID
    return template.yaml_text


def build_contract() -> dict[str, Any]:
    """The contract: ``compiled``, and ``simulations`` keyed by case name."""
    text = template_text()
    compiled: Any = None
    simulations: dict[str, Any] = {}
    for case, inputs in SCRIPTS.items():
        script = SimScript.model_validate({"inputs": inputs})
        result = simulated(text, script, ValidateContext())
        assert isinstance(result, SimulatedResult) and result.simulation is not None, case
        body = result.model_dump(mode="json")
        compiled = body["compiled"] if compiled is None else compiled
        assert body["compiled"] == compiled, case
        simulations[case] = body["simulation"]
    # As the wire carries it.
    return json.loads(json.dumps({"compiled": compiled, "simulations": simulations}))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the template simulations fixture.")
    parser.add_argument("--write", action="store_true", help="rewrite the checked-in file")
    args = parser.parse_args(argv)
    return write_or_check(build_contract(), CONTRACT_PATH, write=args.write, module=MODULE)


if __name__ == "__main__":
    sys.exit(main())

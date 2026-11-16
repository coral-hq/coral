"""Spike 1: does ``_can_use_tool_gate`` enforce a TOOL_CALL DENY on a connector MCP tool?

Run from the repository root::

    uv run --no-sync python docs/coral/decisions/probes/spike_01.py [--model <id>]

Each case installs a policy evaluator that denies ``PHASE_TOOL_CALL`` and allows
every other phase, then scripts one call to the stdio probe tool
``mcp__probe__touch``. ``pass`` needs every case to keep the tool from running.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.e2e._harness_probes import cli_unavailable_reason
from tests.e2e.coral._claude_sdk_kit import cli_versions, run_probe_case

RERUN = "uv run --no-sync python docs/coral/decisions/probes/spike_01.py --model {model}"
# The two prompts Claude Code's auto-mode classifier sends through the same base URL.
CLASSIFIER_STAGES = (
    "Err on the side of blocking",
    "Review the classification process and follow it carefully",
)
CLASSIFIER_ALLOWS = tuple(
    {"responses": [{"text": "<block>no</block>"}] * 20, "match": stage, "required_tools": []}
    for stage in CLASSIFIER_STAGES
)
CASES = (
    ("bypassPermissions", "bypassPermissions", ()),
    ("default", "default", ()),
    ("auto", "auto", ()),
    ("auto, classifier allows", "auto", CLASSIFIER_ALLOWS),
)


def _deny_tool_calls(phases: list[tuple[str, str | None]]):
    async def evaluate(phase: str, payload: dict) -> SimpleNamespace:
        phases.append((phase, payload.get("name")))
        denied = phase == "PHASE_TOOL_CALL"
        action = "POLICY_ACTION_DENY" if denied else "POLICY_ACTION_ALLOW"
        return SimpleNamespace(action=action, reason="probe deny")

    return evaluate


async def _probe(model: str) -> dict:
    root = Path(tempfile.mkdtemp(prefix="spike-01-"))
    cases = []
    for index, (label, mode, classifier_queues) in enumerate(CASES):
        phases: list[tuple[str, str | None]] = []
        observed = await run_probe_case(
            root / str(index),
            model=model,
            permission_mode=mode,
            turn_timeout_s=180,
            tool="touch",
            arguments={"note": "spike-01"},
            policy_evaluator=_deny_tool_calls(phases),
            extra_queues=classifier_queues,
        )
        cases.append(
            {
                "case": label,
                "gate_consulted": any(phase == "PHASE_TOOL_CALL" for phase, _ in phases),
                "tool_ran": "touched spike-01" in observed["marker"],
                "policy_phases": phases,
                **observed,
            }
        )
    return {
        "spike": 1,
        "verdict": "fail" if any(case["tool_ran"] for case in cases) else "pass",
        **cli_versions(),
        "cases": cases,
        "rerun": RERUN.format(model=model),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="mock-spk03-probe")
    args = parser.parse_args()
    missing = cli_unavailable_reason("claude")
    if missing is not None:
        rerun = RERUN.format(model=args.model)
        print(json.dumps({"spike": 1, "verdict": "blocked", "missing": missing, "rerun": rerun}))
        return
    print(json.dumps(asyncio.run(_probe(args.model)), indent=1))


if __name__ == "__main__":
    main()

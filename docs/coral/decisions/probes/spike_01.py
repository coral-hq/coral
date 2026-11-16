"""Spike 1: does a Coral claude-sdk session enforce a TOOL_CALL DENY on a connector MCP tool?

Run from the repository root: ``uv run --no-sync python docs/coral/decisions/probes/spike_01.py``.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.e2e._harness_probes import cli_unavailable_reason
from tests.e2e.coral._claude_sdk_kit import cli_versions, probe_tool, run_probe_case

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


# Deny only the probe tool: denying ToolSearch too would hide the tool before it is called.
def _deny_probe_tool_calls(phases: list[tuple[str, str | None]]):
    async def evaluate(phase: str, payload: dict) -> SimpleNamespace:
        phases.append((phase, payload.get("name")))
        denied = phase == "PHASE_TOOL_CALL" and payload.get("name") == probe_tool("touch")
        action = "POLICY_ACTION_DENY" if denied else "POLICY_ACTION_ALLOW"
        return SimpleNamespace(action=action, reason="probe deny")

    return evaluate


async def _probe(model: str) -> dict:
    cases = []
    for label, mode, classifier_queues in CASES:
        phases: list[tuple[str, str | None]] = []
        observed = await run_probe_case(
            model=model,
            permission_mode=mode,
            turn_timeout_s=180,
            tool="touch",
            arguments={"note": "spike-01"},
            policy_evaluator=_deny_probe_tool_calls(phases),
            extra_queues=classifier_queues,
            coral=True,
        )
        cases.append(
            {
                "case": label,
                "gate_consulted": ("PHASE_TOOL_CALL", probe_tool("touch")) in phases,
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

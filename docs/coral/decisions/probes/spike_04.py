"""Spike 4: does the claude-sdk executor send every model call to a mock ``ANTHROPIC_BASE_URL``?

Run from the repository root: ``uv run --no-sync python docs/coral/decisions/probes/spike_04.py``.
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.e2e._harness_probes import cli_unavailable_reason
from tests.e2e.coral._claude_sdk_kit import cli_versions, run_probe_case

RERUN = "uv run --no-sync python docs/coral/decisions/probes/spike_04.py"
OFF_MACHINE_HOST = "api.example.invalid"


def _passed(case: dict) -> bool:
    clean = case["completed_with_token"] and not case["errors"] and not case["turn_timed_out"]
    reached_mock = case["mock_message_requests"] >= 1 and not case["egress_request_lines"]
    return clean and reached_mock


async def _probe(model: str) -> dict:
    text_only = await run_probe_case(
        model=model, permission_mode="bypassPermissions", turn_timeout_s=120
    )
    with_tool = await run_probe_case(
        model=model,
        permission_mode="bypassPermissions",
        turn_timeout_s=120,
        tool="touch",
        arguments={"note": "spike-04"},
    )
    off_machine = await run_probe_case(
        model=model,
        permission_mode="bypassPermissions",
        turn_timeout_s=120,
        extra_env={"ANTHROPIC_BASE_URL": f"https://{OFF_MACHINE_HOST}"},
    )
    tool_ran = with_tool["marker"] == ["touched spike-04"]
    tool_result_seen = any("TOUCHED-spike-04" in result for result in with_tool["tool_results"])
    recorder_saw_control = any(
        line.startswith(f"CONNECT {OFF_MACHINE_HOST}:443")
        for line in off_machine["egress_request_lines"]
    )
    passed = (
        _passed(text_only)
        and _passed(with_tool)
        and tool_ran
        and tool_result_seen
        and recorder_saw_control
    )
    return {
        "spike": 4,
        "verdict": "pass" if passed else "fail",
        **cli_versions(),
        "cases": [
            {"case": "text only", **text_only},
            {"case": "stdio MCP touch", **with_tool},
            {"case": "control: base URL off the machine", **off_machine},
        ],
        "rerun": RERUN,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="mock-spk03-probe")
    args = parser.parse_args()
    missing = cli_unavailable_reason("claude")
    if missing is not None:
        print(json.dumps({"spike": 4, "verdict": "blocked", "missing": missing, "rerun": RERUN}))
        return
    print(json.dumps(asyncio.run(_probe(args.model)), indent=1))


if __name__ == "__main__":
    main()

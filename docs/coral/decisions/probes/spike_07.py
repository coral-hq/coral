"""Spike 7: how long does the ``claude`` CLI wait for a slow stdio MCP tool?

Run from the repository root::

    uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 30
    uv run --no-sync python docs/coral/decisions/probes/spike_07.py --seconds 10 \\
        --mcp-tool-timeout-ms 3000

The probe tool ``nap`` sleeps ``--seconds``. Without ``--mcp-tool-timeout-ms``
the probe unsets ``MCP_TOOL_TIMEOUT``. The verdict stays ``partial`` because
this probe cannot reach the in-process ``mcp__omnigent__*`` path; it is
``fail`` only when the turn errors or outlives ``--seconds`` plus 120 s.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from tests.e2e._harness_probes import cli_unavailable_reason
from tests.e2e.coral._claude_sdk_kit import cli_versions, run_probe_case

RERUN = "uv run --no-sync python docs/coral/decisions/probes/spike_07.py"
TURN_ALLOWANCE_S = 120


async def _probe(model: str, seconds: float, timeout_ms: int | None) -> dict:
    observed = await run_probe_case(
        Path(tempfile.mkdtemp(prefix="spike-07-")) / "case",
        model=model,
        permission_mode="bypassPermissions",
        turn_timeout_s=seconds + TURN_ALLOWANCE_S,
        tool="nap",
        arguments={"seconds": seconds},
        extra_env={"MCP_TOOL_TIMEOUT": None if timeout_ms is None else str(timeout_ms)},
    )
    finished = observed["completed_with_token"] and not observed["errors"]
    rerun = f"{RERUN} --seconds {seconds:g}"
    if timeout_ms is not None:
        rerun += f" --mcp-tool-timeout-ms {timeout_ms}"
    return {
        "spike": 7,
        "verdict": "partial" if finished else "fail",
        **cli_versions(),
        "cases": [
            {
                "case": f"nap {seconds:g}s, MCP_TOOL_TIMEOUT={timeout_ms or 'unset'}",
                "nap_result_delivered": any("NAPPED-" in r for r in observed["tool_results"]),
                "cli_timed_out_tool": any("timed out" in r for r in observed["tool_results"]),
                **observed,
            }
        ],
        "not_measured": "in-process mcp__omnigent__* tools (needs the runner dispatch bridge)",
        "rerun": rerun,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="mock-spk03-probe")
    parser.add_argument("--seconds", type=float, default=30.0)
    parser.add_argument("--mcp-tool-timeout-ms", type=int)
    args = parser.parse_args()
    missing = cli_unavailable_reason("claude")
    if missing is not None:
        print(json.dumps({"spike": 7, "verdict": "blocked", "missing": missing, "rerun": RERUN}))
        return
    report = asyncio.run(_probe(args.model, args.seconds, args.mcp_tool_timeout_ms))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()

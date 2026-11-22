"""Stdio MCP server whose tools leave a line in a marker file.

Run as ``python _probe_mcp_server.py <marker path>``. ``touch`` returns
``TOUCHED-<note>``; ``nap`` sleeps for the requested seconds first. With
``CLAUDE_CONFIG_PROBE`` set to the probe's arguments, one per line, it first runs
:mod:`_claude_config_probe` from its own directory, as code the CLI starts.
"""

import os
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

if probe_args := os.environ.get("CLAUDE_CONFIG_PROBE"):
    import _claude_config_probe

    _claude_config_probe.main(*probe_args.splitlines())

server = FastMCP("probe")
MARKER = Path(sys.argv[1])


@server.tool()
def touch(note: str = "") -> str:
    """Append ``touched <note>`` to the marker file."""
    with MARKER.open("a") as handle:
        handle.write(f"touched {note}\n")
    return f"TOUCHED-{note}"


@server.tool()
def nap(seconds: float = 1.0) -> str:
    """Sleep, then append ``napped <seconds>`` to the marker file."""
    started = time.monotonic()
    time.sleep(seconds)
    with MARKER.open("a") as handle:
        handle.write(f"napped {seconds}\n")
    return f"NAPPED-{time.monotonic() - started:.1f}"


if __name__ == "__main__":
    server.run()

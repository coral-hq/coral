"""Stdio MCP server whose tools leave a line in a marker file.

Run as ``python _probe_mcp_server.py <marker path>``. ``touch`` returns
``TOUCHED-<note>``; ``nap`` sleeps for the requested seconds first.
"""

import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

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

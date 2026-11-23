"""What each harness is known to support, shown as capability chips on a profile."""

from __future__ import annotations

from typing import Literal

from coral.validate.preflight import CLAUDE_SDK_HARNESS

CapabilityState = Literal["supported", "unsupported", "unknown"]

# ponytail: a static table until harnesses report capabilities themselves; unbenched
# capabilities stay "unknown" rather than guessed.
_HARNESS_CAPABILITIES: dict[str, dict[str, CapabilityState]] = {
    CLAUDE_SDK_HARNESS: {
        "steering": "unknown",
        "tool_gating": "supported",
        "fs_read_only": "supported",
        "usage_reporting": "unknown",
    },
}
_UNKNOWN: dict[str, CapabilityState] = dict.fromkeys(
    ("steering", "tool_gating", "fs_read_only", "usage_reporting"), "unknown"
)


def harness_capabilities(harness: str) -> dict[str, CapabilityState]:
    """Each capability's state for *harness*; every one is ``unknown`` for an unlisted harness."""
    return dict(_HARNESS_CAPABILITIES.get(harness, _UNKNOWN))

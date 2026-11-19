"""Text an agent can act on for a missing done-when item, and for a whole verdict."""

from __future__ import annotations

from coral.evidence.ir import Missing, MissingItem

# Printed paths and commands are cut so a reply stays small.
_SHOWN_MAX = 200


def item_message(item: MissingItem) -> str:
    """One line for one item, e.g. "`pytest -q` ran before the last change to `a.py`; ..."."""
    run = _shown(item.run)
    if item.reason == "never_ran":
        return (
            f"`{run}` has not run in this step; run it as its own command, or last in an "
            "`&&` chain."
        )
    if item.reason == "unverified":
        return (
            f"Coral could not check `{run}` because the worktree could not be read; run it again."
        )
    if item.reason == "predates_change":
        where = f" to `{_shown(item.changed_path)}`" if item.changed_path else ""
        return f"`{run}` ran before the last change{where}; run it again."
    if item.reason == "failed":
        return f"`{run}` failed the last time it ran; fix it and run it again."
    return f"`{run}` did not report an exit code (it may have timed out); run it again."


def verdict_message(verdict: Missing) -> str:
    """Every missing item's line, then what to do."""
    lines = [item_message(item) for item in verdict.items]
    lines.append(
        "Done-when commands must pass after your last change; then call "
        "coral_submit_handoff again."
    )
    return "\n".join(lines)


def _shown(text: str | None) -> str:
    value = (text or "").replace("`", "'").replace("\n", " ")
    return value if len(value) <= _SHOWN_MAX else value[: _SHOWN_MAX - 1] + "…"


__all__ = ["item_message", "verdict_message"]

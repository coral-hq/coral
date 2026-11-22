"""WSP-03 K10 agent / per-item worktree branch keys."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentWorktreeKey:
    """Stable coordinates for one writer's worktree."""

    run_id: str
    node_id: str
    item_path: tuple[str, ...]
    agent: str
    roster_index: int
    attempt: int = 1

    def branch_name(self) -> str:
        """``coral/r-<run12>/a-<node8>-<scope8>-m<roster>-t<attempt>``."""
        run12 = _short(self.run_id, 12)
        node8 = _short(self.node_id, 8)
        scope8 = _short("/".join(self.item_path) or "-", 8)
        return f"coral/r-{run12}/a-{node8}-{scope8}-m{self.roster_index}-t{self.attempt}"

    def full_ref(self) -> str:
        return f"refs/heads/{self.branch_name()}"


def agent_worktree_key(
    *,
    run_id: str,
    node_id: str,
    item_path: tuple[str, ...] = (),
    agent: str,
    roster_index: int,
    attempt: int = 1,
) -> AgentWorktreeKey:
    """Build the K10 key for one agent worktree."""
    if roster_index < 0 or attempt < 1:
        raise ValueError("roster_index must be >= 0 and attempt >= 1")
    if not run_id or not node_id or not agent:
        raise ValueError("run_id, node_id and agent are required")
    return AgentWorktreeKey(
        run_id=run_id,
        node_id=node_id,
        item_path=item_path,
        agent=agent,
        roster_index=roster_index,
        attempt=attempt,
    )


def _short(value: str, length: int) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()
    return digest[:length]

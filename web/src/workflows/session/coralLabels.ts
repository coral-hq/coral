import type { Conversation } from "@/hooks/useConversations";

// Labels Coral puts on the sessions of a run. Clients cannot write `coral.*`
// labels, so the web can trust them.

export const RUN_ID_LABEL = "coral.run_id";
export const ROLE_LABEL = "coral.role";
const ANCHOR_ROLE = "run";

function label(row: Pick<Conversation, "labels">, key: string): string | null {
  const labels: unknown = row.labels;
  if (typeof labels !== "object" || labels === null) return null;
  const value = (labels as Record<string, unknown>)[key];
  return typeof value === "string" && value !== "" ? value : null;
}

/** The run a session belongs to (its anchor, orchestrator or a step), if any. */
export function runIdOf(row: Pick<Conversation, "labels">): string | null {
  return label(row, RUN_ID_LABEL);
}

/** The session's part in its run: `run` (the anchor), `orchestrator` or `step`. */
export function runRoleOf(row: Pick<Conversation, "labels">): string | null {
  return runIdOf(row) === null ? null : label(row, ROLE_LABEL);
}

/** The session is a run's anchor, where the run's gate prompts live. */
export function isRunAnchor(row: Pick<Conversation, "labels">): boolean {
  return runRoleOf(row) === ANCHOR_ROLE;
}

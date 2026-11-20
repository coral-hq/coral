import type { Conversation } from "@/hooks/useConversations";
import contract from "./workflowInbox.contract.json";

// The web/backend contract of the workflow Inbox, built by the backend's own
// serializers (`tests/coral/api/inbox_contract.py`); web tests read it here.

/** One `GET /v1/coral/inbox` page: a pause alert, then a gate alert. */
export const CONTRACT_INBOX_PAGE: unknown = contract.inbox_page;

/** The anchor's pending prompts: the gate prompt, then a step prompt mirrored onto it. */
export const CONTRACT_PENDING_ELICITATIONS: readonly Record<string, unknown>[] =
  contract.pending_elicitations;

/** The contract's run anchor as a session-list row; fields it leaves out take test defaults. */
export function contractAnchorRow(overrides: Partial<Conversation> = {}): Conversation {
  return {
    object: "conversation",
    title: "Ship the bridge",
    created_at: 1_767_268_000,
    updated_at: 1_767_268_000,
    permission_level: null,
    archived: false,
    ...contract.anchor_row,
    ...overrides,
  };
}

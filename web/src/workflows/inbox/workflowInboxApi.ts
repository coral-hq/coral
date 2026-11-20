import { authenticatedFetch } from "@/lib/identity";
import type { CoralOperations } from "../api/generated/coralApi";
import type {
  WorkflowAlert,
  WorkflowAlertAction,
  WorkflowAlertKind,
  WorkflowInboxPage,
} from "../api/types";

// The workflow Inbox feed (`GET /v1/coral/inbox`) and its ack routes. Gate answers
// go through Omnigent's elicitation resolve route (`approve()`), not here.

type BulkAck = CoralOperations["coral_ack_alerts"];

const INBOX_PATH = "/v1/coral/inbox";
const BULK_ACK_PATH = "/v1/coral/inbox/ack" satisfies BulkAck["path"];
export const WORKFLOW_INBOX_PAGE_SIZE = 100;

const KINDS: ReadonlySet<string> = new Set<WorkflowAlertKind>([
  "gate",
  "question",
  "pause",
  "watchdog",
  "overdue",
  "reaction",
  "run_completed",
  "run_failed",
  "run_cancelled",
]);
const ACTIONS: ReadonlySet<string> = new Set<WorkflowAlertAction>([
  "answer",
  "open_run",
  "mark_read",
  "resume",
  "cancel",
]);

/** A failed feed or ack request; a 404 on the feed means the server has no workflow Inbox. */
export class WorkflowInboxError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "WorkflowInboxError";
    this.status = status;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

const isString = (value: unknown): value is string => typeof value === "string";
const isOptionalString = (value: unknown): value is string | null =>
  value === null || typeof value === "string";

/** One feed item, or `null` when it is not an alert this client can show. */
function parseAlert(item: unknown): WorkflowAlert | null {
  if (!isRecord(item)) return null;
  const { kind, priority, created_at: createdAt, actions, outcomes } = item;
  const valid =
    isString(item.alert_id) &&
    isString(item.run_id) &&
    isString(item.run_title) &&
    isString(kind) &&
    KINDS.has(kind) &&
    (priority === "normal" || priority === "low") &&
    typeof createdAt === "number" &&
    Number.isFinite(createdAt) &&
    isString(item.title) &&
    isString(item.message) &&
    isOptionalString(item.step_label) &&
    isOptionalString(item.node_id) &&
    Array.isArray(actions) &&
    isString(item.deep_link) &&
    isOptionalString(item.approve_link) &&
    isOptionalString(item.elicitation_id) &&
    isOptionalString(item.session_id) &&
    Array.isArray(outcomes) &&
    isOptionalString(item.pause_reason);
  if (!valid) return null;
  return {
    ...(item as unknown as WorkflowAlert),
    actions: actions.filter((action): action is WorkflowAlertAction => ACTIONS.has(action)),
    outcomes: outcomes.filter(isString),
  };
}

/**
 * Read a feed page, dropping items this client cannot show.
 *
 * :raises WorkflowInboxError: The payload is not a feed page.
 */
export function parseWorkflowInboxPage(payload: unknown): WorkflowInboxPage {
  if (
    !isRecord(payload) ||
    !Array.isArray(payload.data) ||
    !isOptionalString(payload.next_cursor)
  ) {
    throw new WorkflowInboxError("Invalid workflow inbox response", 502);
  }
  return {
    data: payload.data.map(parseAlert).filter((alert) => alert !== null),
    next_cursor: payload.next_cursor,
  };
}

/** One page of the caller's open alerts, normal priority first, newest first. */
export async function fetchWorkflowInboxPage(
  after?: string,
  signal?: AbortSignal,
): Promise<WorkflowInboxPage> {
  const params = new URLSearchParams({ limit: String(WORKFLOW_INBOX_PAGE_SIZE) });
  if (after !== undefined) params.set("after", after);
  const response = await authenticatedFetch(`${INBOX_PATH}?${params.toString()}`, { signal });
  if (!response.ok) {
    throw new WorkflowInboxError(
      `Failed to load workflow alerts (${response.status})`,
      response.status,
    );
  }
  return parseWorkflowInboxPage(await response.json());
}

/** Mark an alert read; the JSON body keeps plain cross-site forms from posting it. */
export async function ackWorkflowAlert(alertId: string): Promise<void> {
  const response = await authenticatedFetch(`${INBOX_PATH}/${encodeURIComponent(alertId)}/ack`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
  if (!response.ok) {
    throw new WorkflowInboxError(
      `Failed to mark the alert read (${response.status})`,
      response.status,
    );
  }
}

/**
 * Mark a run's open low-priority alerts read, as opening the run does; alerts that ask
 * for an answer or an action stay open.
 *
 * :raises WorkflowInboxError: The server refused or has no workflow Inbox (404).
 */
export async function ackRunAlerts(runId: string): Promise<BulkAck["response"]> {
  const body: BulkAck["body"] = { run_id: runId };
  const response = await authenticatedFetch(BULK_ACK_PATH, {
    method: "POST" satisfies BulkAck["method"],
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    throw new WorkflowInboxError(
      `Failed to mark the run's alerts read (${response.status})`,
      response.status,
    );
  }
  return (await response.json()) as BulkAck["response"];
}

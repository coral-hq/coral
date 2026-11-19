import type { Conversation } from "@/hooks/useConversations";
import type { InboxKindEntry, InboxRawElicitation } from "@/lib/inboxKinds";
import type { WorkflowAlert } from "../api/types";
import { isRunAnchor, runIdOf } from "../session/coralLabels";

// Pure helpers of the workflow Inbox kind: which prompts are gates, how prompts
// and alerts become entries (one per gate), and what the sidebar badge adds.

const GATE_ELICITATION_ID = /^coral_gate_[0-9a-f]{32}$/;

/** What a gate prompt on a run anchor says, read defensively from the raw event. */
export interface GatePrompt {
  /** The anchor whose snapshot held the prompt. */
  sessionId: string;
  message: string | null;
  outcomes: readonly string[];
  runId: string | null;
  runTitle: string | null;
  nodeId: string | null;
  /** `null` is the single local user (or an owner the prompt does not name). */
  runOwner: string | null;
  /** Epoch seconds the visit opened. */
  openedAt: number | null;
}

/** One gate: its prompt, its alert, or both, joined by elicitation id. */
export interface WorkflowGateEntryData {
  type: "gate";
  elicitationId: string | null;
  alert: WorkflowAlert | null;
  prompt: GatePrompt | null;
}

export interface WorkflowAlertEntryData {
  type: "alert";
  alert: WorkflowAlert;
}

export type WorkflowEntryData = WorkflowGateEntryData | WorkflowAlertEntryData;

function record(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

const text = (value: unknown): string | null => (typeof value === "string" ? value : null);
const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

/**
 * The prompt is a gate this kind shows: a `coral_gate_` id on a run anchor, aimed
 * at the anchor itself. Mirrored or forged prompts stay ordinary approvals.
 */
export function isWorkflowGateEvent({ row, event }: InboxRawElicitation): boolean {
  const id = event.elicitation_id;
  if (typeof id !== "string" || !GATE_ELICITATION_ID.test(id) || !isRunAnchor(row)) return false;
  const target = record(event.params).target_session_id;
  return target === undefined || target === null || target === row.id;
}

function gatePrompt(row: Conversation, event: Record<string, unknown>): GatePrompt {
  const params = record(event.params);
  const coral = record(params.coral);
  const schemaOutcomes = strings(
    record(record(record(params.requestedSchema).properties).decision).enum,
  );
  const openedAt = coral.opened_at;
  return {
    sessionId: row.id,
    message: text(params.message),
    outcomes: schemaOutcomes.length > 0 ? schemaOutcomes : strings(coral.outcomes),
    runId: text(coral.run_id) ?? runIdOf(row),
    runTitle: text(coral.run_title),
    nodeId: text(coral.node_id),
    runOwner: text(coral.run_owner),
    openedAt: typeof openedAt === "number" && Number.isFinite(openedAt) ? openedAt : null,
  };
}

/**
 * The kind's entries: one per gate (its prompt joined with its alert), then one
 * per other alert. A gate alert without a prompt is still a gate entry.
 */
export function workflowEntries(
  alerts: readonly WorkflowAlert[],
  claimed: readonly InboxRawElicitation[],
): InboxKindEntry[] {
  const entries: InboxKindEntry[] = [];
  const gateIds = new Set<string>();
  for (const { row, event } of claimed) {
    const elicitationId = event.elicitation_id;
    if (typeof elicitationId !== "string" || gateIds.has(elicitationId)) continue;
    gateIds.add(elicitationId);
    const alert = alerts.find((candidate) => candidate.elicitation_id === elicitationId) ?? null;
    const prompt = gatePrompt(row, event);
    const data: WorkflowGateEntryData = { type: "gate", elicitationId, alert, prompt };
    entries.push({
      key: `workflow:gate:${elicitationId}`,
      at: alert?.created_at ?? prompt.openedAt ?? row.updated_at,
      tab: "awaiting",
      data,
    });
  }
  for (const alert of alerts) {
    if (alert.elicitation_id !== null && gateIds.has(alert.elicitation_id)) continue;
    if (alert.kind === "gate") {
      const elicitationId = alert.elicitation_id;
      const data: WorkflowGateEntryData = { type: "gate", elicitationId, alert, prompt: null };
      entries.push({
        key: `workflow:gate:${elicitationId ?? alert.alert_id}`,
        at: alert.created_at,
        tab: "awaiting",
        data,
      });
      continue;
    }
    const data: WorkflowAlertEntryData = { type: "alert", alert };
    entries.push({
      key: `workflow:alert:${alert.alert_id}`,
      at: alert.created_at,
      tab: "unread",
      data,
    });
  }
  return entries;
}

/**
 * Open normal-priority alerts that no anchor's pending count already counts:
 * every non-gate alert, and gate alerts whose anchor is not loaded or reports
 * nothing pending. Low-priority (run-end) alerts are listed but not badged.
 */
export function badgeCount(
  alerts: readonly WorkflowAlert[],
  rows: readonly Pick<Conversation, "id" | "pending_elicitations_count">[],
): number {
  return alerts.filter((alert) => {
    if (alert.priority !== "normal") return false;
    if (alert.kind !== "gate") return true;
    const anchor = rows.find((row) => row.id === alert.session_id);
    return (anchor?.pending_elicitations_count ?? 0) === 0;
  }).length;
}

/** Display fields of a gate, from its alert where there is one, else from its prompt. */
export interface GateView {
  elicitationId: string | null;
  /** The session to answer on: the run anchor. */
  sessionId: string | null;
  runId: string | null;
  runTitle: string;
  title: string;
  stepLabel: string | null;
  nodeId: string | null;
  message: string | null;
  outcomes: readonly string[];
  /** Epoch seconds the gate has waited since. */
  openedAt: number | null;
}

/** Whether the outcomes are an approval: approve, or approve and reject. */
function isApproval(outcomes: readonly string[]): boolean {
  const set = new Set(outcomes);
  return set.has("approve") && [...set].every((label) => label === "approve" || label === "reject");
}

export function gateView({ elicitationId, alert, prompt }: WorkflowGateEntryData): GateView {
  const outcomes = prompt && prompt.outcomes.length > 0 ? prompt.outcomes : (alert?.outcomes ?? []);
  return {
    elicitationId,
    sessionId: alert?.session_id ?? prompt?.sessionId ?? null,
    runId: alert?.run_id ?? prompt?.runId ?? null,
    runTitle: alert?.run_title ?? prompt?.runTitle ?? "Workflow run",
    title: alert?.title ?? (isApproval(outcomes) ? "Approval needed" : "Decision needed"),
    stepLabel: alert?.step_label ?? null,
    nodeId: alert?.node_id ?? prompt?.nodeId ?? null,
    message: prompt?.message ?? alert?.message ?? null,
    outcomes,
    openedAt: alert?.created_at ?? prompt?.openedAt ?? null,
  };
}

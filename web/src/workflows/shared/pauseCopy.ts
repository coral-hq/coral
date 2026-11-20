import type { RunHeader } from "../api/generated/coralApi";

// What a paused run's pill and banner say. Specific copy where the cause's detail code is
// one the engine records, else the server's pause alert copy (`PAUSE_MESSAGES` in
// `coral/alerts/rules.py`), else "The run paused.".

/** A reason the run row can be paused for. */
export type PauseReasonName = NonNullable<RunHeader["pause_reason"]>;

/** One cause of a pause, as the run view lists them; a newer server may send other reasons. */
export interface PauseCauseLike {
  reason: string;
  detail: string;
  subject: string;
}

/** The graph's node names; only `id` and `name` are read. */
export interface GraphNodeNames {
  readonly nodes: readonly { readonly id: string; readonly name?: string | null }[];
}

export interface PauseCopy {
  /** The reason in a few words, `null` for one this client cannot name. */
  label: string | null;
  /** "Paused: <label>", or "Paused" without a label. */
  title: string;
  body: string;
}

/** The server's pause alert copy per reason; a user's own pause has none. */
export const PAUSE_MESSAGES: Readonly<Record<Exclude<PauseReasonName, "user">, string>> = {
  gate: "The run is waiting at a gate.",
  budget: "The run reached its activation cap.",
  plan_limit: "A step reached its plan's usage limit.",
  rejected_calls: "A step kept making calls Coral refused.",
  infra: "A step kept failing to finish its turn.",
  liveness: "A step is waiting for one that can no longer run.",
  authority_revoked: "The run lost the authority it was started with.",
  merge_conflict: "The run's changes conflict with its base branch.",
  failure_path: "A step or one of Coral's own actions failed.",
  engine_upgrade: "The run needs a newer Coral engine.",
  drift: "A session the run uses was changed outside Coral.",
  auth: "A step's harness needs you to sign in again.",
};

/** What the banner says when nothing more specific is known. */
export const UNKNOWN_PAUSE_TEXT = "The run paused.";
/** What a run whose engine state cannot be loaded says. */
export const LOAD_FAILED_TEXT = "This run can’t be loaded. You can still cancel it.";

const LABELS: Readonly<Record<PauseReasonName, string>> = {
  user: "by you",
  failure_path: "step failed",
  infra: "infrastructure",
  plan_limit: "plan limit",
  auth: "sign-in needed",
  budget: "activation cap",
  rejected_calls: "refused calls",
  liveness: "step waiting",
  drift: "session changed",
  authority_revoked: "account access revoked",
  engine_upgrade: "Coral upgraded",
  gate: "gate",
  merge_conflict: "merge conflict",
};

const LIVENESS_DETAIL = /^(\S+) is waiting for (\S+), which can no longer run\.$/;

function isPauseReasonName(reason: string): reason is PauseReasonName {
  return Object.hasOwn(LABELS, reason);
}

/**
 * A node's name as the graph gives it, its id when the name is missing or blank, or `null`
 * when the graph has no such node.
 */
export function nodeLabel(graph: GraphNodeNames | null, nodeId: string): string | null {
  const node = graph?.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) return null;
  return node.name?.trim() ? node.name : node.id;
}

/**
 * The node of an engine slot id `<activation>:<index>`, whose activation is
 * `<node>|<item>|<iteration>`; `null` when the id has neither form.
 */
export function slotNodeId(slotId: string): string | null {
  const end = slotId.lastIndexOf(":");
  if (end < 0) return null;
  const activation = slotId.slice(0, end);
  const bar = activation.indexOf("|");
  return bar > 0 ? activation.slice(0, bar) : null;
}

function failureBody(cause: PauseCauseLike): string {
  if (cause.detail === "attempts_exhausted" && cause.subject !== "") {
    return `Missing evidence: ${cause.subject}.`;
  }
  if (cause.detail === "engine.load_failed") return LOAD_FAILED_TEXT;
  return PAUSE_MESSAGES.failure_path;
}

function livenessBody(cause: PauseCauseLike, graph: GraphNodeNames | null): string {
  const match = LIVENESS_DETAIL.exec(cause.detail);
  const join = match && nodeLabel(graph, match[1]!);
  const source = match && nodeLabel(graph, match[2]!);
  if (join === null || source === null) return PAUSE_MESSAGES.liveness;
  return `${join} is waiting for ${source}, which can no longer run.`;
}

function driftBody(cause: PauseCauseLike, graph: GraphNodeNames | null): string {
  if (cause.detail === "anchor_archived") {
    return "The run’s session was archived. Unarchive it to continue, or cancel.";
  }
  if (cause.detail === "anchor_deleted") {
    return "The run’s session was deleted. The run can only be cancelled.";
  }
  const nodeId = slotNodeId(cause.subject);
  const step = nodeId === null ? null : nodeLabel(graph, nodeId);
  if (step !== null && cause.detail === "pending_input") {
    return `Someone typed into ${step}’s session while Coral was finishing it.`;
  }
  if (step !== null && cause.detail === "post_close") {
    return `${step}’s session kept working after its step closed.`;
  }
  return PAUSE_MESSAGES.drift;
}

/** The banner body for `reason`, made specific by `cause`'s detail when it has one. */
function body(reason: PauseReasonName, cause: PauseCauseLike | null, graph: GraphNodeNames | null) {
  switch (reason) {
    case "user":
      return UNKNOWN_PAUSE_TEXT;
    case "failure_path":
      return cause ? failureBody(cause) : PAUSE_MESSAGES.failure_path;
    case "liveness":
      return cause ? livenessBody(cause, graph) : PAUSE_MESSAGES.liveness;
    case "drift":
      return cause ? driftBody(cause, graph) : PAUSE_MESSAGES.drift;
    case "plan_limit":
      // No reset time reaches the client, so the banner only says that Coral retries.
      return `${PAUSE_MESSAGES.plan_limit} Coral retries periodically.`;
    case "engine_upgrade":
      return "Coral was upgraded; this run cannot continue.";
    case "infra":
    case "auth":
    case "budget":
    case "rejected_calls":
    case "authority_revoked":
    case "gate":
    case "merge_conflict":
      return PAUSE_MESSAGES[reason];
    default: {
      const unhandled: never = reason;
      return unhandled;
    }
  }
}

/** The pause reason in a few words, or `null` for a reason this client cannot name. */
export function pauseLabel(reason: string | null): string | null {
  return reason !== null && isPauseReasonName(reason) ? LABELS[reason] : null;
}

/** "Paused: <label>", or "Paused" for a reason this client cannot name. */
export function pauseTitle(reason: string | null): string {
  const label = pauseLabel(reason);
  return label === null ? "Paused" : `Paused: ${label}`;
}

const known = (reason: string | null | undefined): reason is PauseReasonName =>
  typeof reason === "string" && isPauseReasonName(reason);

/**
 * A paused run's banner: titled by the run's `reason` and explained by its first `cause`
 * (by its own reason and detail). A cause this client cannot name, or none, leaves the
 * run's `reason` to explain it.
 *
 * :param graph: The run's graph, for step names; `null` until it loads.
 */
export function pauseCopy(
  reason: string | null,
  cause: PauseCauseLike | null,
  graph: GraphNodeNames | null,
): PauseCopy {
  const titled = known(reason) ? reason : known(cause?.reason) ? cause.reason : null;
  let text = UNKNOWN_PAUSE_TEXT;
  if (cause !== null && known(cause.reason)) text = body(cause.reason, cause, graph);
  else if (known(reason)) text = body(reason, null, graph);
  return { label: pauseLabel(titled), title: pauseTitle(titled), body: text };
}

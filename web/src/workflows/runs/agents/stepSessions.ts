import type { CompiledGraph, RunDetail, RunView, SlotOut } from "../../api/generated/coralApi";
import { iterationSegment, parseActivationId, slotActivationId } from "../../shared/runIds";

// The sessions of a run's steps, from the detail's slots: which agent of which pass each
// one is, so the run view can open its transcript. A session id the detail does not list
// is not part of the run.

/** One agent of a step and the session it works in (`null` before Coral creates it). */
export interface StepSession {
  /** The engine slot id `<activation>:<roster index>`, as the run view's slots carry it. */
  engineSlotId: string;
  activationId: string;
  /** The activation's pass in its innermost loop; `null` outside a loop. */
  pass: number | null;
  sessionId: string | null;
  nodeId: string;
  role: SlotOut["role"];
  /** A step agent's roster profile; `null` for another role or a roster the graph lacks. */
  profile: string | null;
  /** The step's harness id; `null` for the workspace default. */
  harness: string | null;
  /** The live view's status when it holds the slot, else the detail's. */
  status: SlotOut["status"];
}

/** A step's sessions in one of its activations. */
export interface StepActivationSessions {
  activationId: string;
  pass: number | null;
  sessions: StepSession[];
}

type SlotsDetail = Pick<RunDetail, "slots" | "view">;

const ROLE_TEXT: Readonly<Record<SlotOut["role"], string>> = {
  step_agent: "Step agent",
  orchestrator: "Orchestrator",
  verifier: "Verifier",
  merge_resolver: "Merge resolver",
};

/** How a session's agent is named: its roster profile, else its role. */
export function agentName(session: Pick<StepSession, "profile" | "role">): string {
  return session.profile ?? ROLE_TEXT[session.role];
}

const STATUS_LINES: Partial<Record<SlotOut["status"], string>> = {
  evaluating: "Checking evidence…",
  closing: "Coral is committing this step’s work",
};

/** What Coral is doing with a step's session, when it is doing something. */
export function slotStatusLine(status: SlotOut["status"]): string | null {
  return STATUS_LINES[status] ?? null;
}

/** The roster position an engine slot id ends with; 0 without one, as the server reads it. */
function rosterIndex(engineSlotId: string): number {
  const tail = engineSlotId.slice(engineSlotId.lastIndexOf(":") + 1);
  return /^\d+$/.test(tail) ? Number(tail) : 0;
}

function passOf(activationId: string): number | null {
  const innermost = parseActivationId(activationId)?.iterationPath.at(-1);
  return innermost === undefined ? null : (iterationSegment(innermost)?.pass ?? null);
}

function toSession(slot: SlotOut, graph: CompiledGraph | null, view: RunView | null): StepSession {
  const activationId = slotActivationId(slot.engine_slot_id) ?? slot.engine_slot_id;
  const node = graph?.nodes.find((candidate) => candidate.id === slot.node_id);
  const live = view?.slots.find((candidate) => candidate.id === slot.engine_slot_id);
  return {
    engineSlotId: slot.engine_slot_id,
    activationId,
    pass: passOf(activationId),
    sessionId: slot.session_id,
    nodeId: slot.node_id,
    role: slot.role,
    profile:
      slot.role === "step_agent" ? (node?.roster[rosterIndex(slot.engine_slot_id)] ?? null) : null,
    harness: node?.harness ?? null,
    status: live?.status ?? slot.status,
  };
}

/**
 * A node's sessions grouped by activation, latest first (the view lists activations in the
 * order they began; one it lacks goes last), each group in roster order.
 */
export function stepSessions(
  detail: SlotsDetail,
  graph: CompiledGraph | null,
  nodeId: string,
  view: RunView | null = detail.view,
): StepActivationSessions[] {
  const order = (view ?? detail.view)?.activations.map((activation) => activation.id) ?? [];
  const groups = new Map<string, StepActivationSessions>();
  for (const slot of detail.slots) {
    if (slot.node_id !== nodeId) continue;
    const session = toSession(slot, graph, view);
    const group = groups.get(session.activationId) ?? {
      activationId: session.activationId,
      pass: session.pass,
      sessions: [],
    };
    group.sessions.push(session);
    groups.set(session.activationId, group);
  }
  const rank = (activationId: string) => {
    const index = order.indexOf(activationId);
    return index < 0 ? -1 : index;
  };
  return [...groups.values()]
    .map((group, arrival) => ({ group, arrival }))
    .sort((left, right) => {
      const byRank = rank(right.group.activationId) - rank(left.group.activationId);
      if (byRank !== 0) return byRank;
      return left.arrival - right.arrival;
    })
    .map(({ group }) => ({
      ...group,
      sessions: group.sessions.sort(
        (left, right) => rosterIndex(left.engineSlotId) - rosterIndex(right.engineSlotId),
      ),
    }));
}

/**
 * The run's slot whose session is `sessionId`, or `null` when the run lists no such session.
 * `sessionId` may come from the URL; only an exact match of a listed session counts.
 */
export function runSession(
  detail: SlotsDetail,
  graph: CompiledGraph | null,
  sessionId: string,
  view: RunView | null = detail.view,
): StepSession | null {
  if (sessionId === "") return null;
  const slot = detail.slots.find((candidate) => candidate.session_id === sessionId);
  return slot ? toSession(slot, graph, view) : null;
}

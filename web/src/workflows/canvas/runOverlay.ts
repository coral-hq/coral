import type {
  ActivationView,
  CompiledGraph,
  LoopInfo,
  LoopPassView,
  PauseCause,
  RunView,
} from "../api/generated/coralApi";
import {
  activationNodeId,
  iterationSegment,
  parseActivationId,
  slotActivationId,
  slotNodeId,
  type ActivationIdParts,
} from "../shared/runIds";
import { isFinishedRunStatus } from "../shared/runStatus";

// What the run view knows about each node of the run's graph. A node's state comes from its
// activations in the current loop pass: an earlier pass's outcome never shows while a later
// pass is under way, and a body node the current pass has not reached reads as waiting (or,
// once the run ended, as it last closed).
// Activation counts span every pass. The pass counter is the innermost loop's that holds the
// node. The canvas and the step list both read it.

export type NodeRunState =
  "idle" | "waiting" | "running" | "evaluating" | "closing" | "completed" | "failed" | "skipped";

/** A loop's pass at a node: 1-based, with the loop's limit when it has one. */
export interface NodePass {
  index: number;
  limit: number | null;
}

export interface NodeOverlay {
  state: NodeRunState;
  /** Activations of this node, in every pass. */
  activations: number;
  /** Of them, the closed ones. */
  closed: number;
  /** One of the view's open gate visits is at this node. */
  gateOpen: boolean;
  /** Someone typed into a slot's session of this node. */
  pendingInput: boolean;
  /** A slot's session of this node was changed outside Coral. */
  drift: boolean;
  /** The orchestrator has a decision to make at this node. */
  decisionOpen: boolean;
  /** Pause causes whose subject is this node, one of its activations or one of its slots. */
  causes: PauseCause[];
  /** The pass of the innermost loop that holds this node, on the node's own path. */
  pass: NodePass | null;
  /** The graph lists evidence checks for this node. */
  evidence: boolean;
}

// Higher wins among a node's current activations (its list items).
const RANK: Readonly<Record<NodeRunState, number>> = {
  idle: 0,
  skipped: 1,
  completed: 2,
  failed: 3,
  waiting: 4,
  running: 5,
  evaluating: 6,
  closing: 7,
};

const STATE_TEXT: Readonly<Record<NodeRunState, string>> = {
  idle: "Not started",
  waiting: "Waiting",
  running: "Running",
  evaluating: "Checking evidence…",
  closing: "Committing",
  completed: "Completed",
  failed: "Failed",
  skipped: "Skipped",
};

function activationState({ status, outcome }: ActivationView): NodeRunState {
  switch (status) {
    case "evaluating":
      return "evaluating";
    case "running":
    case "starting":
      return "running";
    case "closed":
      return outcome ?? "completed";
    default:
      // `ready`, `waiting_join`, or a status a newer engine sends: it exists, not yet running.
      return "waiting";
  }
}

/** `prefix` is `itemPath` or one of its leading item paths (a loop around a list). */
const holdsItems = (prefix: string, itemPath: string) =>
  prefix === "" || itemPath === prefix || itemPath.startsWith(`${prefix}/`);

/**
 * The counter of the loop with `backArrowId` inside the iteration `enclosing`, on the item
 * path the activation is on (a loop inside a list counts each item on its own).
 */
function findCounter(
  counters: readonly LoopPassView[],
  backArrowId: string,
  itemPath: string,
  enclosing: readonly string[],
): LoopPassView | null {
  const scope = enclosing.join("/");
  return (
    counters.find(
      (counter) =>
        counter.back_arrow_id === backArrowId &&
        counter.iteration_path.join("/") === scope &&
        holdsItems(counter.item_path.join("/"), itemPath),
    ) ?? null
  );
}

/** Whether an activation is in its loops' current passes: no loop has moved past it. */
function isCurrent(parts: ActivationIdParts, counters: readonly LoopPassView[]): boolean {
  return parts.iterationPath.every((segment, index) => {
    const parsed = iterationSegment(segment);
    if (parsed === null) return true;
    const enclosing = parts.iterationPath.slice(0, index);
    const counter = findCounter(counters, parsed.backArrowId, parts.itemPath, enclosing);
    return counter === null || counter.pass_index <= parsed.pass;
  });
}

/**
 * The pass of the innermost loop that holds a node, walking its loops from the outermost
 * down the current passes; `null` when that loop has not started on the node's path. While
 * the node is current this is the counter of its latest activation's enclosing path.
 */
function nodePass(
  loops: readonly LoopInfo[],
  counters: readonly LoopPassView[],
  itemPath: string,
): NodePass | null {
  const enclosing: string[] = [];
  for (const [index, loop] of loops.entries()) {
    const counter = findCounter(counters, loop.back_arrow_id, itemPath, enclosing);
    if (counter === null) return null;
    if (index === loops.length - 1) return { index: counter.pass_index, limit: loop.limit };
    enclosing.push(`${loop.back_arrow_id}:${counter.pass_index}`);
  }
  return null;
}

/** The node a cause's subject names: a node id, a slot id or an activation id. */
function causeNodeId(subject: string, nodes: ReadonlyMap<string, NodeOverlay>): string | null {
  if (nodes.has(subject)) return subject;
  for (const nodeId of [slotNodeId(subject), activationNodeId(subject)]) {
    if (nodeId !== null && nodes.has(nodeId)) return nodeId;
  }
  return null;
}

/**
 * Each node's run state, keyed by node id in graph order; every node is idle while `view`
 * is `null`. Pure: memoize it on `(graph, view)`.
 */
export function runOverlay(
  graph: CompiledGraph,
  view: RunView | null,
): ReadonlyMap<string, NodeOverlay> {
  const nodes = new Map<string, NodeOverlay>();
  for (const node of graph.nodes) {
    nodes.set(node.id, {
      state: "idle",
      activations: 0,
      closed: 0,
      gateOpen: false,
      pendingInput: false,
      drift: false,
      decisionOpen: false,
      causes: [],
      pass: null,
      evidence: (node.evidence?.items.length ?? 0) > 0,
    });
  }
  if (view === null) return nodes;
  const at = (nodeId: string | null) => (nodeId === null ? undefined : nodes.get(nodeId));
  const raise = (entry: NodeOverlay, state: NodeRunState) => {
    if (RANK[state] > RANK[entry.state]) entry.state = state;
  };
  const counters = view.loop_pass_indexes;

  // Each node's activations in the current pass, its latest one in any pass, and the
  // outcome of its latest closed one.
  const current = new Set<string>();
  const latest = new Map<string, ActivationIdParts>();
  const lastClosed = new Map<string, NodeRunState>();
  for (const activation of view.activations) {
    const parts = parseActivationId(activation.id);
    const entry = at(parts?.nodeId ?? null);
    if (!parts || !entry) continue;
    entry.activations += 1;
    if (activation.status === "closed") {
      entry.closed += 1;
      lastClosed.set(parts.nodeId, activationState(activation));
    }
    latest.set(parts.nodeId, parts);
    if (isCurrent(parts, counters)) {
      current.add(activation.id);
      raise(entry, activationState(activation));
    }
  }
  const ended = isFinishedRunStatus(view.status);
  for (const [nodeId, entry] of nodes) {
    // It ran in an earlier pass, and the current one has not reached it: yet, while the run
    // goes on; never, once it ended, when the node shows how it last closed.
    if (entry.activations > 0 && entry.state === "idle") {
      entry.state = ended ? (lastClosed.get(nodeId) ?? "idle") : "waiting";
    }
    // The validator (V5) nests loops that share a node, so body size orders them.
    const loops = graph.analysis.loops
      .filter((loop) => loop.body.includes(nodeId))
      .sort((outer, inner) => inner.body.length - outer.body.length);
    if (loops.length > 0)
      entry.pass = nodePass(loops, counters, latest.get(nodeId)?.itemPath ?? "");
  }

  for (const slot of view.slots) {
    const entry = at(slotNodeId(slot.id));
    if (!entry) continue;
    const activationId = slotActivationId(slot.id);
    if (slot.status === "closing" && activationId !== null && current.has(activationId)) {
      raise(entry, "closing");
    }
    entry.pendingInput ||= slot.pending_input;
    entry.drift ||= slot.drift;
  }
  for (const token of view.open_gates) {
    const entry = at(activationNodeId(token));
    if (entry) entry.gateOpen = true;
  }
  for (const decision of view.open_decisions) {
    const entry = at(activationNodeId(decision));
    if (entry) entry.decisionOpen = true;
  }
  for (const cause of view.causes) {
    at(causeNodeId(cause.subject, nodes))?.causes.push(cause);
  }
  return nodes;
}

/** A node's state in words; an open gate is the owner's turn. */
export function nodeStatusText(overlay: NodeOverlay): string {
  return overlay.gateOpen ? "Waiting for you" : STATE_TEXT[overlay.state];
}

/** "pass N of M", or "pass N" for a loop without a limit. */
export function passText(pass: NodePass): string {
  return pass.limit === null ? `pass ${pass.index}` : `pass ${pass.index} of ${pass.limit}`;
}

/** The node has something stalling it that the owner may need to look at. */
export function isStalled(overlay: NodeOverlay): boolean {
  return overlay.pendingInput || overlay.drift || overlay.causes.length > 0;
}

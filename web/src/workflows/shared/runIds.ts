// The engine's ids as the run view carries them. An activation is
// `<node>|<item path>|<iteration path>`, each path joined by `/`; an iteration segment is
// `<back arrow>:<pass>`, outermost loop first; a slot is `<activation>:<roster index>`.

/** An activation id's parts; `itemPath` is the joined path, as counters compare it. */
export interface ActivationIdParts {
  nodeId: string;
  itemPath: string;
  iterationPath: readonly string[];
}

/** The node of an activation id `<node>|<item>|<iteration>`; `null` without that form. */
export function activationNodeId(activationId: string): string | null {
  const bar = activationId.indexOf("|");
  return bar > 0 ? activationId.slice(0, bar) : null;
}

/** An activation id's node, item path and iteration segments; `null` without a node. */
export function parseActivationId(activationId: string): ActivationIdParts | null {
  const first = activationId.indexOf("|");
  if (first <= 0) return null;
  const last = activationId.lastIndexOf("|");
  const nodeId = activationId.slice(0, first);
  if (last === first) return { nodeId, itemPath: activationId.slice(first + 1), iterationPath: [] };
  const iterations = activationId.slice(last + 1);
  return {
    nodeId,
    itemPath: activationId.slice(first + 1, last),
    iterationPath: iterations === "" ? [] : iterations.split("/"),
  };
}

/** An iteration segment `<back arrow>:<pass>`; `null` when it has no positive pass. */
export function iterationSegment(segment: string): { backArrowId: string; pass: number } | null {
  const colon = segment.lastIndexOf(":");
  const pass = Number(segment.slice(colon + 1));
  if (colon <= 0 || !Number.isInteger(pass) || pass < 1) return null;
  return { backArrowId: segment.slice(0, colon), pass };
}

/** The activation of an engine slot id `<activation>:<index>`; `null` without a `:`. */
export function slotActivationId(slotId: string): string | null {
  const end = slotId.lastIndexOf(":");
  return end < 0 ? null : slotId.slice(0, end);
}

/**
 * The node of an engine slot id `<activation>:<index>`, whose activation is
 * `<node>|<item>|<iteration>`; `null` when the id has neither form.
 */
export function slotNodeId(slotId: string): string | null {
  const activationId = slotActivationId(slotId);
  return activationId === null ? null : activationNodeId(activationId);
}

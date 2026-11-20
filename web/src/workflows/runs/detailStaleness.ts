import type { RunDetail, RunHeader, RunView } from "../api/generated/coralApi";

// When the run's detail no longer matches its streamed view: a gate opened or closed, a
// slot appeared, or a slot started without the session the detail knows. The check runs
// only on a trigger (a snapshot, a header change, or a change to the view's gates or
// slots), so a mismatch the server keeps cannot drive a refetch loop.

/** What the staleness triggers compare between two stream states. */
export interface StalenessMarks {
  view: RunView | null;
  header: RunHeader | null;
}

/** The detail fields the view is checked against. */
export type StalenessDetail = Pick<RunDetail, "gates" | "slots">;

/** Whether `detail` is behind `view`'s gates or slots; never for a run with no view. */
export function detailIsStale(detail: StalenessDetail, view: RunView | null): boolean {
  if (view === null) return false;
  const detailTokens = new Set(detail.gates.map((gate) => gate.token));
  const viewTokens = new Set(view.open_gates);
  if (view.open_gates.some((token) => !detailTokens.has(token))) return true;
  if (detail.gates.some((gate) => !viewTokens.has(gate.token))) return true;
  const slotsById = new Map(detail.slots.map((slot) => [slot.engine_slot_id, slot]));
  return view.slots.some((slot) => {
    const known = slotsById.get(slot.id);
    if (known === undefined) return true;
    return slot.status !== "pending" && known.session_id === null;
  });
}

/**
 * Whether going from `previous` to `next` is a staleness trigger: the first view, a new
 * header, or a view whose gates or slots changed. The stream controller copies only what a
 * patch touches, so an entry that leaves both alone keeps the same arrays.
 */
export function isStalenessTrigger(previous: StalenessMarks | null, next: StalenessMarks): boolean {
  if (previous === null) return next.view !== null;
  if (next.header !== null && next.header !== previous.header) return true;
  if (next.view === null || next.view === previous.view) return false;
  if (previous.view === null) return true;
  return (
    next.view.open_gates !== previous.view.open_gates || next.view.slots !== previous.view.slots
  );
}

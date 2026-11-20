import type { CompiledGraph, RunDetail, RunHeader, RunOutcome } from "../api/generated/coralApi";
import contract from "./runView.contract.json";
import viewPatchText from "./viewPatch.contract.json?raw";

// The run view's web/backend contract, recorded from the backend's own run stream and
// serializers (`tests/coral/api/run_view_contract.py`) and patch applier
// (`tests/coral/runview/view_patch_contract.py`); web tests read it here.

/** One server-sent event as the stream sent it; a line it lacked is `null` (`[DONE]` has only `data`). */
export interface ContractEvent {
  event: string | null;
  id: string | null;
  data: string;
}

/** The scripted run's milestones, in order. */
export type ContractMilestone = keyof typeof contract.live_marks;

/** The run's pinned graph: `gated`, with `pytest -q` as `implement`'s evidence. */
export const CONTRACT_GRAPH = contract.graph as unknown as CompiledGraph;

/** One stream opened right after the start and read live to `[DONE]`. */
export const CONTRACT_LIVE: readonly ContractEvent[] = contract.live;

/** `CONTRACT_LIVE`'s events as one response body. */
export const CONTRACT_LIVE_RAW: string = contract.live_raw;

/** The seq the live tail holds at each milestone (`gate2_answered` is also `finished`). */
export const CONTRACT_LIVE_MARKS: Readonly<Record<ContractMilestone, number>> = contract.live_marks;

/** The seq a dropped live tail resumes after: the first gate's. */
export const CONTRACT_RESUME_AFTER: number = contract.resume_after;

/** A reconnect after the end with `Last-Event-ID: CONTRACT_RESUME_AFTER`. */
export const CONTRACT_RESUMED: readonly ContractEvent[] = contract.resumed;

/** A fresh connect after the end: the snapshot, then `[DONE]`. */
export const CONTRACT_FINAL_SNAPSHOT: readonly ContractEvent[] = contract.final_snapshot;

/** The detail while the first gate is open. */
export const CONTRACT_DETAIL_GATE_PASS1 = contract.detail_gate_pass1 as unknown as RunDetail;

/** The detail while the second gate (loop pass 2) is open. */
export const CONTRACT_DETAIL_GATE_PASS2 = contract.detail_gate_pass2 as unknown as RunDetail;

/** The detail of the completed run. */
export const CONTRACT_FINAL_DETAIL = contract.final_detail as unknown as RunDetail;

/** The completed run's outcome, with its checkout command. */
export const CONTRACT_OUTCOME = contract.outcome as unknown as RunOutcome;

/** A pause reason the server's alerts name; a user's own pause has no alert copy. */
export type AlertedPauseReason = Exclude<NonNullable<RunHeader["pause_reason"]>, "user">;

/**
 * What a pause alert says for each reason but `user`, and for a reason it cannot name: the
 * fallback bodies step 5's copy table must match. The rest of the copy is the table's own.
 */
export const CONTRACT_PAUSE_MESSAGES: {
  readonly by_reason: Readonly<Record<AlertedPauseReason, string>>;
  readonly unknown: string;
} = contract.pause_messages;

/** One `apply_view_patch` case: its result, its refusal, or a refusal only the web makes. */
export interface ViewPatchCase {
  name: string;
  view: Record<string, unknown>;
  patch: readonly { op: string; path: string; value?: unknown }[];
  result?: Record<string, unknown>;
  error?: true;
  client_error?: true;
}

/** Every patch case, parsed from the raw text so `__proto__` keys stay own members. */
export const VIEW_PATCH_CASES: readonly ViewPatchCase[] = (
  JSON.parse(viewPatchText) as { cases: ViewPatchCase[] }
).cases;

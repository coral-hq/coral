import { describe, expect, it } from "vitest";
import type { RunDetail, RunHeader, RunView } from "../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS1 } from "../fixtures/runViewContract";
import { applyViewPatch, type JsonObject } from "../stream/viewPatch";
import { detailIsStale, isStalenessTrigger } from "./detailStaleness";

const DETAIL = CONTRACT_DETAIL_GATE_PASS1;
const VIEW = DETAIL.view!;
const HEADER: RunHeader = {
  status: "running",
  pause_reason: null,
  version: 6,
  finished_at: null,
  allowed_actions: ["pause", "cancel"],
  load_error: null,
};

/** `view` after `patch`, copied only where the patch writes, as the stream controller does. */
function patched(view: RunView, patch: { op: string; path: string; value?: unknown }[]): RunView {
  return applyViewPatch(view as unknown as JsonObject, patch) as unknown as RunView;
}

function detailWith(changes: Partial<RunDetail>): RunDetail {
  return { ...DETAIL, ...changes };
}

describe("detailIsStale", () => {
  it("is not stale for the detail read with the view", () => {
    // WHY: the recorded detail and its own view agree, so nothing is refetched.
    expect(detailIsStale(DETAIL, VIEW)).toBe(false);
  });

  it("is stale when the view opens a gate the detail does not hold", () => {
    // WHY: the gate card needs the new visit's token and context from the detail.
    const view = patched(VIEW, [
      { op: "add", path: "/open_gates/-", value: "approve_change||a4:2:1" },
    ]);
    expect(detailIsStale(DETAIL, view)).toBe(true);
  });

  it("is stale when the detail holds a gate the view closed", () => {
    // WHY: an answered gate must leave the detail's gate list.
    const view = patched(VIEW, [{ op: "remove", path: "/open_gates/0" }]);
    expect(detailIsStale(DETAIL, view)).toBe(true);
  });

  it("is stale when the view has a slot the detail does not know", () => {
    // WHY: a new step's session id comes only from the detail.
    const view = patched(VIEW, [
      {
        op: "add",
        path: "/slots/-",
        value: { id: "implement||a4:2:0", status: "pending", pending_input: false, drift: false },
      },
    ]);
    expect(detailIsStale(DETAIL, view)).toBe(true);
  });

  it("waits for a session only once the slot has left pending", () => {
    // WHY: a pending slot has no session yet; a started one without its session id is behind.
    const noSession = detailWith({
      slots: DETAIL.slots.map((slot) => ({ ...slot, session_id: null })),
    });
    const pending = patched(VIEW, [{ op: "replace", path: "/slots/0/status", value: "pending" }]);
    expect(detailIsStale(noSession, pending)).toBe(false);
    expect(detailIsStale(noSession, VIEW)).toBe(true);
  });

  it("is never stale for a run with no view", () => {
    // WHY: an unloadable run has nothing to compare, so it must not refetch.
    expect(detailIsStale(DETAIL, null)).toBe(false);
  });
});

describe("isStalenessTrigger", () => {
  it("fires on the first view, not before it", () => {
    // WHY: a snapshot is a trigger; a state with no view yet has nothing to check.
    expect(isStalenessTrigger(null, { view: VIEW, header: HEADER })).toBe(true);
    expect(isStalenessTrigger(null, { view: null, header: null })).toBe(false);
  });

  it("fires on a new header", () => {
    // WHY: a status change can come with gate or slot changes the detail lacks.
    expect(
      isStalenessTrigger({ view: VIEW, header: HEADER }, { view: VIEW, header: { ...HEADER } }),
    ).toBe(true);
  });

  it("fires when an entry touches the gates or the slots", () => {
    // WHY: those are the only view parts the detail mirrors.
    const marks = { view: VIEW, header: HEADER };
    const slots = patched(VIEW, [{ op: "replace", path: "/slots/0/status", value: "working" }]);
    const gates = patched(VIEW, [{ op: "remove", path: "/open_gates/0" }]);
    expect(isStalenessTrigger(marks, { view: slots, header: HEADER })).toBe(true);
    expect(isStalenessTrigger(marks, { view: gates, header: HEADER })).toBe(true);
  });

  it("stays quiet for an entry that touches neither, or no change", () => {
    // WHY: activation progress alone never refetches the detail, so a lasting mismatch cannot loop.
    const marks = { view: VIEW, header: HEADER };
    const activations = patched(VIEW, [
      { op: "replace", path: "/activations/2/status", value: "evaluating" },
    ]);
    expect(isStalenessTrigger(marks, { view: activations, header: HEADER })).toBe(false);
    expect(isStalenessTrigger(marks, { view: VIEW, header: HEADER })).toBe(false);
    expect(isStalenessTrigger(marks, { view: null, header: HEADER })).toBe(false);
  });

  it("fires when a view arrives after none", () => {
    // WHY: a snapshot after an unloadable state replaces the whole view.
    expect(isStalenessTrigger({ view: null, header: HEADER }, { view: VIEW, header: HEADER })).toBe(
      true,
    );
  });
});

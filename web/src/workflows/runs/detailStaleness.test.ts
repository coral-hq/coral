import { describe, expect, it } from "vitest";
import type { PauseCause, RunDetail, RunHeader, RunView } from "../api/generated/coralApi";
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

  it("is stale when the view's pause causes differ from the detail's", () => {
    // WHY: the causes decide which steps the detail offers to retry, so a step that blocks
    // or a restart that fails must reread it rather than wait for the 30 s poll.
    const blocked = { reason: "failure_path", detail: "blocked", subject: "implement||a4:2:0" };
    const paused = patched(VIEW, [
      { op: "replace", path: "/status", value: "paused" },
      { op: "add", path: "/causes/0", value: blocked },
    ]);
    expect(detailIsStale(DETAIL, paused)).toBe(true);
    const failedRestart = { ...blocked, detail: "restart:workspace.head_moved" };
    const restarted = patched(paused, [{ op: "replace", path: "/causes/0", value: failedRestart }]);
    expect(detailIsStale(detailWith({ causes: paused.causes }), restarted)).toBe(true);
    expect(detailIsStale(detailWith({ causes: restarted.causes }), restarted)).toBe(false);
    expect(detailIsStale(detailWith({ causes: restarted.causes }), VIEW)).toBe(true);
  });

  it("compares the causes by value and in order, by reason, detail and subject", () => {
    // WHY: the detail's causes are a fresh JSON copy of the view's, so only a real change in
    // what a cause says, or which comes first, may reread it.
    const blocked: PauseCause = {
      reason: "failure_path",
      detail: "blocked",
      subject: "implement||a4:2:0",
    };
    const closed: PauseCause = {
      reason: "failure_path",
      detail: "session.closed",
      subject: "implement||a4:1:0",
    };
    const view = patched(VIEW, [
      { op: "add", path: "/causes/-", value: blocked },
      { op: "add", path: "/causes/-", value: closed },
    ]);
    const copy = JSON.parse(JSON.stringify(view.causes)) as RunView["causes"];
    expect(detailIsStale(detailWith({ causes: copy }), view)).toBe(false);
    expect(detailIsStale(detailWith({ causes: [closed, blocked] }), view)).toBe(true);
    expect(detailIsStale(detailWith({ causes: [blocked] }), view)).toBe(true);
    for (const changed of [
      { ...closed, reason: "infra" as const },
      { ...closed, detail: "session.deleted" },
      { ...closed, subject: "implement||a4:2:0" },
    ]) {
      expect(detailIsStale(detailWith({ causes: [blocked, changed] }), view)).toBe(true);
    }
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
    // WHY: the detail mirrors those view parts.
    const marks = { view: VIEW, header: HEADER };
    const slots = patched(VIEW, [{ op: "replace", path: "/slots/0/status", value: "working" }]);
    const gates = patched(VIEW, [{ op: "remove", path: "/open_gates/0" }]);
    expect(isStalenessTrigger(marks, { view: slots, header: HEADER })).toBe(true);
    expect(isStalenessTrigger(marks, { view: gates, header: HEADER })).toBe(true);
  });

  it("fires when an entry touches the causes", () => {
    // WHY: a cause can change while the header stays the same, such as a second step blocking.
    const marks = { view: VIEW, header: HEADER };
    const causes = patched(VIEW, [
      {
        op: "add",
        path: "/causes/0",
        value: { reason: "failure_path", detail: "blocked", subject: "implement||a4:2:0" },
      },
    ]);
    expect(isStalenessTrigger(marks, { view: causes, header: HEADER })).toBe(true);
  });

  it("stays quiet for an entry that touches none of them, or no change", () => {
    // WHY: activation progress alone never refetches the detail, so a lasting mismatch cannot loop.
    const marks = { view: VIEW, header: HEADER };
    const activations = patched(VIEW, [
      { op: "replace", path: "/activations/2/status", value: "evaluating" },
    ]);
    expect(isStalenessTrigger(marks, { view: activations, header: HEADER })).toBe(false);
    expect(isStalenessTrigger(marks, { view: VIEW, header: HEADER })).toBe(false);
    expect(isStalenessTrigger(marks, { view: null, header: HEADER })).toBe(false);
  });

  it("stays quiet for entries after a cause change that leave the causes alone", () => {
    // WHY: once a cause change has been checked, timers and activation progress never ask
    // again, even while the detail still lags the view.
    const blocked = { reason: "failure_path", detail: "blocked", subject: "implement||a4:2:0" };
    const paused = patched(VIEW, [{ op: "add", path: "/causes/0", value: blocked }]);
    const timers = patched(paused, [
      { op: "add", path: "/armed_timer_keys/-", value: "watchdog_remind:implement||a4:2" },
    ]);
    const progress = patched(timers, [
      { op: "replace", path: "/activations/2/status", value: "evaluating" },
    ]);
    expect(timers.causes).toBe(paused.causes);
    expect(
      isStalenessTrigger({ view: paused, header: HEADER }, { view: timers, header: HEADER }),
    ).toBe(false);
    expect(
      isStalenessTrigger({ view: timers, header: HEADER }, { view: progress, header: HEADER }),
    ).toBe(false);
    expect(detailIsStale(DETAIL, progress)).toBe(true);
  });

  it("fires when a view arrives after none", () => {
    // WHY: a snapshot after an unloadable state replaces the whole view.
    expect(isStalenessTrigger({ view: null, header: HEADER }, { view: VIEW, header: HEADER })).toBe(
      true,
    );
  });
});

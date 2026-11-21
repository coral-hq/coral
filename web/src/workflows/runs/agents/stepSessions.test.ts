import { describe, expect, it } from "vitest";
import type { CompiledGraph, RunDetail, RunView, SlotOut } from "../../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../../fixtures/runViewContract";
import { agentName, runSession, slotStatusLine, stepSessions } from "./stepSessions";

const DETAIL = CONTRACT_DETAIL_GATE_PASS2;
const PASS1 = DETAIL.slots.find((candidate) => candidate.engine_slot_id === "implement||a4:1:0")!;
const PASS2 = DETAIL.slots.find((candidate) => candidate.engine_slot_id === "implement||a4:2:0")!;

function slot(overrides: Partial<SlotOut>): SlotOut {
  return { ...PASS1, ...overrides };
}

function withSlots(slots: SlotOut[], view: RunView | null = DETAIL.view): RunDetail {
  return { ...DETAIL, slots, view };
}

function graphWith(roster: string[], harness: string | null = null): CompiledGraph {
  return {
    ...CONTRACT_GRAPH,
    nodes: CONTRACT_GRAPH.nodes.map((node) =>
      node.id === "implement" ? { ...node, roster, harness } : node,
    ),
  };
}

describe("stepSessions", () => {
  it("groups a step's sessions by activation, latest pass first", () => {
    // WHY: the newest pass is the one a person wants to read; earlier passes stay reachable.
    const groups = stepSessions(DETAIL, CONTRACT_GRAPH, "implement");
    expect(groups.map((group) => [group.activationId, group.pass])).toEqual([
      ["implement||a4:2", 2],
      ["implement||a4:1", 1],
    ]);
    expect(groups[0]!.sessions).toEqual([
      {
        engineSlotId: "implement||a4:2:0",
        activationId: "implement||a4:2",
        pass: 2,
        sessionId: PASS2.session_id,
        nodeId: "implement",
        role: "step_agent",
        profile: "implementer",
        harness: null,
        status: "closed",
      },
    ]);
    expect(groups[1]!.sessions.map((session) => session.sessionId)).toEqual([PASS1.session_id]);
  });

  it("takes each slot's status from the live view, else from the detail", () => {
    // WHY: the stream is newer than the detail read (the page's one source of status).
    const live: RunView = {
      ...DETAIL.view!,
      slots: DETAIL.view!.slots.map((view) =>
        view.id === "implement||a4:2:0" ? { ...view, status: "closing" } : view,
      ),
    };
    const fromView = stepSessions(DETAIL, CONTRACT_GRAPH, "implement", live);
    expect(fromView[0]!.sessions[0]!.status).toBe("closing");
    // A slot the view does not hold yet keeps the detail's status.
    const extra = slot({
      engine_slot_id: "implement||a4:3:0",
      session_id: "s3",
      status: "briefed",
    });
    const later = stepSessions(withSlots([...DETAIL.slots, extra]), CONTRACT_GRAPH, "implement");
    expect(later.at(-1)!.sessions[0]!.status).toBe("briefed");
  });

  it("puts an activation the view lacks after the known ones, in the detail's order", () => {
    const unknown = slot({ engine_slot_id: "implement||a4:9:0", session_id: "s9" });
    const groups = stepSessions(withSlots([unknown, PASS1, PASS2]), CONTRACT_GRAPH, "implement");
    expect(groups.map((group) => group.activationId)).toEqual([
      "implement||a4:2",
      "implement||a4:1",
      "implement||a4:9",
    ]);
  });

  it("names each agent by its roster position and the step's harness", () => {
    // WHY: two agents of one step are told apart by profile; other roles by their role.
    const second = slot({ engine_slot_id: "implement||a4:1:1", session_id: "reviewer-session" });
    const verifier = slot({
      engine_slot_id: "implement||a4:1:2",
      session_id: "verifier-session",
      role: "verifier",
    });
    const groups = stepSessions(
      withSlots([verifier, second, PASS1]),
      graphWith(["implementer", "reviewer"], "claude-native"),
      "implement",
    );
    expect(
      groups[0]!.sessions.map((session) => [session.sessionId, session.profile, session.role]),
    ).toEqual([
      [PASS1.session_id, "implementer", "step_agent"],
      ["reviewer-session", "reviewer", "step_agent"],
      ["verifier-session", null, "verifier"],
    ]);
    expect(groups[0]!.sessions.every((session) => session.harness === "claude-native")).toBe(true);
  });

  it("keeps a slot that has no session yet, and finds nothing for another node", () => {
    const pending = slot({
      engine_slot_id: "implement||a4:1:0",
      session_id: null,
      status: "pending",
    });
    const groups = stepSessions(withSlots([pending]), CONTRACT_GRAPH, "implement");
    expect(groups[0]!.sessions[0]!.sessionId).toBeNull();
    expect(stepSessions(DETAIL, CONTRACT_GRAPH, "approve_change")).toEqual([]);
    // Without the graph there is no profile or harness to show.
    expect(stepSessions(DETAIL, null, "implement")[0]!.sessions[0]!).toMatchObject({
      profile: null,
      harness: null,
    });
  });
});

describe("runSession", () => {
  it("finds a session only among the run's own slots", () => {
    // WHY: `?agent=` comes from the URL; only a session the run lists may be opened.
    expect(runSession(DETAIL, CONTRACT_GRAPH, PASS2.session_id!)).toMatchObject({
      sessionId: PASS2.session_id,
      nodeId: "implement",
      pass: 2,
    });
    for (const agent of [
      "",
      "evil",
      DETAIL.anchor_session_id,
      "__proto__",
      ` ${PASS2.session_id}`,
      PASS2.session_id!.toUpperCase(),
    ]) {
      expect(runSession(DETAIL, CONTRACT_GRAPH, agent)).toBeNull();
    }
  });

  it("never matches a slot that has no session", () => {
    const pending = slot({ session_id: null });
    expect(runSession(withSlots([pending]), CONTRACT_GRAPH, "null")).toBeNull();
    expect(runSession(withSlots([pending]), CONTRACT_GRAPH, "")).toBeNull();
  });
});

describe("agentName", () => {
  it("names an agent by its profile, else by its role", () => {
    expect(agentName({ profile: "implementer", role: "step_agent" })).toBe("implementer");
    expect(agentName({ profile: null, role: "verifier" })).toBe("Verifier");
    expect(agentName({ profile: null, role: "merge_resolver" })).toBe("Merge resolver");
    expect(agentName({ profile: null, role: "step_agent" })).toBe("Step agent");
  });
});

describe("slotStatusLine", () => {
  it("says what Coral is doing with a step's session", () => {
    expect(slotStatusLine("evaluating")).toBe("Checking evidence…");
    expect(slotStatusLine("closing")).toBe("Coral is committing this step’s work");
    for (const status of ["pending", "working", "closed", "briefed"] as const) {
      expect(slotStatusLine(status)).toBeNull();
    }
  });
});

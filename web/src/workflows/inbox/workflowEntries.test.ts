import { describe, expect, it } from "vitest";
import type { Conversation } from "@/hooks/useConversations";
import type { WorkflowAlert } from "../api/types";
import {
  CONTRACT_INBOX_PAGE,
  CONTRACT_PENDING_ELICITATIONS,
  contractAnchorRow,
} from "../fixtures/workflowInboxContract";
import { parseWorkflowInboxPage } from "./workflowInboxApi";
import {
  badgeCount,
  isWorkflowGateEvent,
  workflowEntries,
  type WorkflowGateEntryData,
} from "./workflowEntries";

const ALERTS = parseWorkflowInboxPage(CONTRACT_INBOX_PAGE).data;
const PAUSE_ALERT = ALERTS[0]!;
const GATE_ALERT = ALERTS[1]!;
const GATE_EVENT = CONTRACT_PENDING_ELICITATIONS[0]!;
const MIRRORED_EVENT = CONTRACT_PENDING_ELICITATIONS[1]!;
const GATE_ID = "coral_gate_00000000000000000000000000000001";
const ANCHOR = contractAnchorRow();

function withParams(event: Record<string, unknown>, params: unknown): Record<string, unknown> {
  return { ...event, params };
}

function gateParams(overrides: Record<string, unknown>): Record<string, unknown> {
  return { ...(GATE_EVENT.params as Record<string, unknown>), ...overrides };
}

function stepRow(): Conversation {
  return contractAnchorRow({
    id: "step_session",
    labels: { "coral.run_id": ANCHOR.labels["coral.run_id"]!, "coral.role": "step" },
  });
}

describe("isWorkflowGateEvent", () => {
  it("claims the contract's gate prompt and leaves the step prompt mirrored onto the anchor", () => {
    // WHY: one card per gate; a step's own approval must stay an ordinary approval card.
    expect(isWorkflowGateEvent({ row: ANCHOR, event: GATE_EVENT })).toBe(true);
    expect(isWorkflowGateEvent({ row: ANCHOR, event: MIRRORED_EVENT })).toBe(false);
  });

  it("claims a gate prompt aimed at the anchor itself or at no session", () => {
    // WHY: the wire sends an unset target as null; a missing key or the anchor's own id mean the same.
    const { target_session_id: _target, ...noTarget } = gateParams({});
    expect(
      isWorkflowGateEvent({
        row: ANCHOR,
        event: withParams(GATE_EVENT, gateParams({ target_session_id: ANCHOR.id })),
      }),
    ).toBe(true);
    expect(isWorkflowGateEvent({ row: ANCHOR, event: withParams(GATE_EVENT, noTarget) })).toBe(
      true,
    );
  });

  it("leaves a gate-shaped prompt mirrored from a step, or found anywhere but a run anchor", () => {
    // WHY: a step could publish a coral_gate_ id; only the anchor's own prompts are gates.
    const mirrored = withParams(GATE_EVENT, gateParams({ target_session_id: "step_session" }));
    expect(isWorkflowGateEvent({ row: ANCHOR, event: mirrored })).toBe(false);
    expect(isWorkflowGateEvent({ row: stepRow(), event: GATE_EVENT })).toBe(false);
    expect(isWorkflowGateEvent({ row: contractAnchorRow({ labels: {} }), event: GATE_EVENT })).toBe(
      false,
    );
    expect(
      isWorkflowGateEvent({
        row: contractAnchorRow({ labels: undefined as unknown as Record<string, string> }),
        event: GATE_EVENT,
      }),
    ).toBe(false);
  });

  it.each([
    ["a numeric id", { ...GATE_EVENT, elicitation_id: 7 }],
    ["a missing id", { params: GATE_EVENT.params }],
    ["an Omnigent id", { ...GATE_EVENT, elicitation_id: `elicit_${"0".repeat(32)}` }],
    ["a short gate id", { ...GATE_EVENT, elicitation_id: "coral_gate_123" }],
    ["an upper-case gate id", { ...GATE_EVENT, elicitation_id: `coral_gate_${"A".repeat(32)}` }],
    ["a non-string target", withParams(GATE_EVENT, gateParams({ target_session_id: 5 }))],
  ])("does not claim a prompt with %s", (_name, event) => {
    // WHY: a malformed prompt must neither throw nor hide as a gate; it stays an approval.
    expect(isWorkflowGateEvent({ row: ANCHOR, event })).toBe(false);
  });

  it.each([
    ["no params", { elicitation_id: GATE_ID }],
    ["null params", withParams(GATE_EVENT, null)],
    ["list params", withParams(GATE_EVENT, ["mode"])],
  ])("claims an anchor's gate id with %s without throwing", (_name, event) => {
    // WHY: the id and anchor decide the claim; the card falls back to the alert's fields.
    expect(isWorkflowGateEvent({ row: ANCHOR, event })).toBe(true);
  });
});

describe("workflowEntries", () => {
  it("joins the contract's gate prompt and gate alert into one awaiting entry", () => {
    // WHY: the prompt and its alert are one gate, so the Inbox shows one card.
    const entries = workflowEntries(ALERTS, [{ row: ANCHOR, event: GATE_EVENT }]);
    expect(entries.map(({ key, tab, at }) => ({ key, tab, at }))).toEqual([
      { key: `workflow:gate:${GATE_ID}`, tab: "awaiting", at: GATE_ALERT.created_at },
      { key: `workflow:alert:${PAUSE_ALERT.alert_id}`, tab: "unread", at: PAUSE_ALERT.created_at },
    ]);
    const gate = entries[0]!.data as WorkflowGateEntryData;
    expect(gate.type).toBe("gate");
    expect(gate.elicitationId).toBe(GATE_ID);
    expect(gate.alert).toEqual(GATE_ALERT);
    expect(gate.prompt).toMatchObject({
      sessionId: ANCHOR.id,
      outcomes: ["approve", "reject"],
      runId: GATE_ALERT.run_id,
      runOwner: "alice",
      runTitle: "Ship the bridge",
      nodeId: "approve_change",
    });
    expect(gate.prompt?.message).toContain("Approve the change?");
    expect(entries[1]!.data).toEqual({ type: "alert", alert: PAUSE_ALERT });
  });

  it("shows a gate alert whose prompt is missing as a gate entry that can be answered", () => {
    // WHY: the engine answers without the in-memory prompt, so the alert alone is a card.
    const [entry] = workflowEntries([GATE_ALERT], []);
    expect(entry).toMatchObject({ key: `workflow:gate:${GATE_ID}`, tab: "awaiting" });
    expect(entry!.data).toEqual({
      type: "gate",
      elicitationId: GATE_ID,
      alert: GATE_ALERT,
      prompt: null,
    });
  });

  it("shows a gate prompt with no alert, timed by when its visit opened", () => {
    // WHY: the prompt can arrive before the feed refreshes; it still sorts by its opening.
    const coral = {
      ...(gateParams({}).coral as Record<string, unknown>),
      opened_at: 1_767_260_000,
    };
    const event = withParams(GATE_EVENT, gateParams({ coral }));
    const entries = workflowEntries([], [{ row: ANCHOR, event }]);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ key: `workflow:gate:${GATE_ID}`, at: 1_767_260_000 });
    expect((entries[0]!.data as WorkflowGateEntryData).alert).toBeNull();
  });

  it("keeps one entry for a gate prompt seen twice", () => {
    // WHY: a re-published gate keeps its id; it must not become two cards.
    const entries = workflowEntries(
      [],
      [
        { row: ANCHOR, event: GATE_EVENT },
        { row: ANCHOR, event: GATE_EVENT },
      ],
    );
    expect(entries).toHaveLength(1);
  });

  it("builds an entry from a claimed prompt with malformed params", () => {
    // WHY: a claimed prompt the kind cannot read must not throw the Inbox away.
    const row = contractAnchorRow({ updated_at: 1_767_000_000 });
    const [entry] = workflowEntries(
      [],
      [{ row, event: { elicitation_id: GATE_ID, params: null } }],
    );
    expect(entry).toMatchObject({ key: `workflow:gate:${GATE_ID}`, at: 1_767_000_000 });
    expect((entry!.data as WorkflowGateEntryData).prompt).toMatchObject({
      sessionId: row.id,
      message: null,
      outcomes: [],
      runId: row.labels["coral.run_id"],
      runOwner: null,
    });
  });
});

describe("badgeCount", () => {
  const lowAlert: WorkflowAlert = {
    ...PAUSE_ALERT,
    alert_id: "f".repeat(32),
    kind: "run_completed",
    priority: "low",
    title: "Run completed",
    actions: ["open_run", "mark_read"],
  };

  it("counts the normal alerts that no anchor prompt already counts", () => {
    // WHY: the anchor's pending count already badges its gate; the pause has no prompt.
    expect(badgeCount(ALERTS, [ANCHOR])).toBe(1);
  });

  it("counts a gate alert whose anchor is not loaded or reports nothing pending", () => {
    // WHY: a gate whose prompt is missing must still reach the badge.
    expect(badgeCount(ALERTS, [])).toBe(2);
    expect(badgeCount(ALERTS, [contractAnchorRow({ pending_elicitations_count: 0 })])).toBe(2);
  });

  it("counts every normal alert that is not a gate, whatever its anchor holds", () => {
    // WHY: only a gate's prompt is the alert itself; a pause is never in the pending count.
    expect(badgeCount([{ ...PAUSE_ALERT, session_id: ANCHOR.id }], [ANCHOR])).toBe(1);
  });

  it("leaves low-priority run-end alerts out of the badge", () => {
    // WHY: run-end alerts are listed but not badged until they can be acked on open.
    expect(badgeCount([...ALERTS, lowAlert], [ANCHOR])).toBe(1);
  });
});

// CORAL(S37): Inbox extension kinds registry and partition tests (new file).
import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, onTestFinished, vi } from "vitest";
import type { Conversation } from "@/hooks/useConversations";
import type { InboxSource } from "./inbox";
import {
  inboxKindsBadgeCount,
  inboxKindsIncomplete,
  partitionElicitations,
  registerInboxKind,
  resetInboxKindsForTests,
  useInboxKinds,
  type InboxKind,
  type InboxKindEntry,
} from "./inboxKinds";

afterEach(() => {
  cleanup();
  resetInboxKindsForTests();
});

function row(id: string): Conversation {
  return {
    id,
    object: "conversation",
    title: id,
    created_at: 1,
    updated_at: 1,
    labels: {},
    permission_level: null,
    pending_elicitations_count: 1,
  };
}

/** A kind that claims elicitation ids starting with `prefix`. */
function kind(id: string, overrides: Partial<InboxKind> = {}, prefix = `${id}_`): InboxKind {
  return {
    id,
    claims: ({ event }) => String(event.elicitation_id).startsWith(prefix),
    entries: () => [],
    badgeCount: 0,
    incomplete: false,
    loading: false,
    error: null,
    summary: (count) => `${count} ${id}`,
    silences: () => false,
    render: () => null,
    ...overrides,
  };
}

describe("inbox kind registry", () => {
  it("adds kinds in order, replaces by id in place and keeps a stable snapshot", () => {
    const { result, rerender } = renderHook(() => useInboxKinds());
    const empty = result.current;
    expect(empty).toEqual([]);
    rerender();
    expect(result.current).toBe(empty);

    act(() => {
      registerInboxKind(kind("first"));
      registerInboxKind(kind("second"));
    });
    expect(result.current.map((registered) => registered.id)).toEqual(["first", "second"]);
    const registered = result.current;
    rerender();
    expect(result.current).toBe(registered);

    act(() => {
      registerInboxKind(kind("first", { badgeCount: 3 }));
    });
    expect(result.current.map(({ id, badgeCount }) => [id, badgeCount])).toEqual([
      ["first", 3],
      ["second", 0],
    ]);
  });

  it("unregisters only its own registration, even of the same kind object", () => {
    const { result } = renderHook(() => useInboxKinds());
    const workflow = kind("workflow");
    let unregisterFirst = () => {};
    let unregisterAgain = () => {};
    act(() => {
      unregisterFirst = registerInboxKind(workflow);
      unregisterAgain = registerInboxKind(workflow);
    });

    act(() => unregisterFirst());
    expect(result.current.map((registered) => registered.id)).toEqual(["workflow"]);
    act(() => {
      unregisterAgain();
      unregisterAgain();
    });
    expect(result.current).toEqual([]);
  });

  it("resets to no kinds", () => {
    registerInboxKind(kind("workflow"));
    resetInboxKindsForTests();
    const { result } = renderHook(() => useInboxKinds());
    expect(result.current).toEqual([]);
  });
});

describe("a kind that throws", () => {
  it("contributes nothing wherever it throws, and is warned about once", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    onTestFinished(() => warn.mockRestore());
    const boom = () => {
      throw new Error("kind bug");
    };
    const faulty = kind("faulty", {
      claims: boom,
      entries: boom,
      summary: boom,
      silences: boom,
    });
    for (const field of ["badgeCount", "incomplete", "loading", "error"] as const) {
      Object.defineProperty(faulty, field, { get: boom });
    }
    registerInboxKind(faulty);
    const { result } = renderHook(() => useInboxKinds());
    const [guarded] = result.current;

    const { unclaimed, claimed } = partitionElicitations(result.current, [
      { row: row("anchor"), pendingElicitations: [{ elicitation_id: "faulty_1" }] },
    ]);
    expect(unclaimed[0]!.pendingElicitations).toEqual([{ elicitation_id: "faulty_1" }]);
    expect(claimed.size).toBe(0);
    expect(guarded!.entries([])).toEqual([]);
    expect(guarded!.summary(1)).toBe("");
    expect(guarded!.silences(row("anchor"))).toBe(false);
    expect([guarded!.loading, guarded!.error]).toEqual([false, null]);
    expect(inboxKindsBadgeCount(result.current)).toBe(0);
    expect(inboxKindsIncomplete(result.current)).toBe(false);
    expect(warn).toHaveBeenCalledOnce();
    expect(String(warn.mock.calls[0]![0])).toContain('Inbox kind "faulty" failed');
  });

  it("answers a malformed result as nothing", () => {
    registerInboxKind(
      kind("odd", {
        badgeCount: Number.NaN,
        entries: () => null as unknown as InboxKindEntry[],
        summary: () => 3 as unknown as string,
      }),
    );
    const { result } = renderHook(() => useInboxKinds());
    expect(inboxKindsBadgeCount(result.current)).toBe(0);
    expect(result.current[0]!.entries([])).toEqual([]);
    expect(result.current[0]!.summary(1)).toBe("");
  });
});

describe("partitionElicitations", () => {
  const sources: InboxSource[] = [
    {
      row: row("anchor"),
      pendingElicitations: [{ elicitation_id: "gate_1" }, { elicitation_id: "elicit_1" }],
    },
    { row: row("plain"), pendingElicitations: [{ elicitation_id: "elicit_2" }] },
  ];

  it("is the identity with no kind registered", () => {
    const { unclaimed, claimed } = partitionElicitations([], sources);
    expect(unclaimed).toBe(sources);
    expect(claimed.size).toBe(0);
    expect(inboxKindsBadgeCount([])).toBe(0);
    expect(inboxKindsIncomplete([])).toBe(false);
  });

  it("moves claimed events to their kind and keeps every other event in its source", () => {
    const { unclaimed, claimed } = partitionElicitations([kind("gate")], sources);

    expect(unclaimed).toEqual([
      { row: sources[0]!.row, pendingElicitations: [{ elicitation_id: "elicit_1" }] },
      sources[1],
    ]);
    // A source the kind claimed nothing from is passed through as is.
    expect(unclaimed[1]).toBe(sources[1]);
    expect(claimed.get("gate")).toEqual([
      { row: sources[0]!.row, event: { elicitation_id: "gate_1" } },
    ]);
  });

  it("gives an event to the first kind that claims it", () => {
    const first = kind("first", {}, "gate_");
    const second = kind("second", {}, "gate_");
    const { claimed } = partitionElicitations([first, second], sources);
    expect(claimed.get("first")).toHaveLength(1);
    expect(claimed.has("second")).toBe(false);
  });

  it("sums badge counts and reports any incomplete kind", () => {
    const kinds = [kind("a", { badgeCount: 2 }), kind("b", { badgeCount: 1, incomplete: true })];
    expect(inboxKindsBadgeCount(kinds)).toBe(3);
    expect(inboxKindsIncomplete(kinds)).toBe(true);
  });
});

import { describe, expect, it } from "vitest";
import type {
  ActivationView,
  CompiledGraph,
  PauseCause,
  RunView,
  SlotView,
} from "../api/generated/coralApi";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_FINAL_DETAIL,
  CONTRACT_GRAPH,
  CONTRACT_LIVE,
  CONTRACT_LIVE_MARKS,
} from "../fixtures/runViewContract";
import { applyViewPatch, type JsonObject } from "../stream/viewPatch";
import { nodeStatusText, passText, runOverlay, type NodeOverlay } from "./runOverlay";

const EMPTY: RunView = {
  status: "running",
  causes: [],
  activations: [],
  slots: [],
  open_decisions: [],
  open_gates: [],
  loop_pass_indexes: [],
  armed_timer_keys: [],
};

const view = (partial: Partial<RunView>): RunView => ({ ...EMPTY, ...partial });

/** The live recording's view at entry `seq`, folded from its snapshot and patches. */
function viewAt(seq: number): RunView {
  let folded: JsonObject | null = null;
  for (const event of CONTRACT_LIVE) {
    if (event.event !== "snapshot" && event.event !== "entry") continue;
    const frame = JSON.parse(event.data) as {
      seq: number;
      view?: JsonObject;
      patch?: { op: string; path: string; value?: unknown }[];
    };
    if (frame.seq > seq) break;
    folded = frame.view ?? applyViewPatch(folded!, frame.patch!);
  }
  return folded as unknown as RunView;
}

function activation(
  id: string,
  status: ActivationView["status"],
  outcome: ActivationView["outcome"] = null,
): ActivationView {
  return { id, status, outcome };
}

function slot(id: string, status: SlotView["status"], flags: Partial<SlotView> = {}): SlotView {
  return { id, status, pending_input: false, drift: false, ...flags };
}

const of = (overlay: ReadonlyMap<string, NodeOverlay>, nodeId: string) => overlay.get(nodeId)!;

describe("runOverlay", () => {
  it("shows every node idle with no counter before the run's view arrives", () => {
    // WHY: nothing has happened that the client knows of, so nothing is claimed.
    const overlay = runOverlay(CONTRACT_GRAPH, null);
    expect([...overlay.keys()]).toEqual(["start", "implement", "approve_change", "end"]);
    for (const entry of overlay.values()) {
      expect(entry).toMatchObject({ state: "idle", activations: 0, closed: 0, pass: null });
    }
  });

  it("flags the steps whose graph lists evidence checks", () => {
    // WHY: the shield marks where Coral checks commands before a handoff is accepted.
    const overlay = runOverlay(CONTRACT_GRAPH, EMPTY);
    expect([...overlay].map(([id, entry]) => [id, entry.evidence])).toEqual([
      ["start", false],
      ["implement", true],
      ["approve_change", false],
      ["end", false],
    ]);
  });

  it.each<[string, ActivationView[], SlotView[], NodeOverlay["state"]]>([
    [
      "a closing slot",
      [activation("implement||", "evaluating")],
      [slot("implement||:0", "closing")],
      "closing",
    ],
    ["an evaluating activation", [activation("implement||", "evaluating")], [], "evaluating"],
    ["a running activation", [activation("implement||", "running")], [], "running"],
    ["a starting activation", [activation("implement||", "starting")], [], "running"],
    ["a ready activation", [activation("implement||", "ready")], [], "waiting"],
    ["a join still waiting", [activation("implement||", "waiting_join")], [], "waiting"],
    ["a failed activation", [activation("implement||", "closed", "failed")], [], "failed"],
    ["a completed activation", [activation("implement||", "closed", "completed")], [], "completed"],
    ["a skipped activation", [activation("implement||", "closed", "skipped")], [], "skipped"],
    ["no activation", [], [], "idle"],
  ])("reads %s as its state", (_name, activations, slots, expected) => {
    // WHY: one node's state follows what its activation and its slots are doing.
    expect(of(runOverlay(CONTRACT_GRAPH, view({ activations, slots })), "implement").state).toBe(
      expected,
    );
  });

  it.each<[string, ActivationView[], SlotView[], number | null, NodeOverlay["state"]]>([
    [
      "the current pass over an earlier one",
      [
        activation("implement||a4:1", "closed", "completed"),
        activation("implement||a4:2", "running"),
      ],
      [],
      2,
      "running",
    ],
    [
      "a completed current pass over a failed earlier one",
      [
        activation("implement||a4:1", "closed", "failed"),
        activation("implement||a4:2", "closed", "completed"),
      ],
      [],
      2,
      "completed",
    ],
    [
      "an earlier pass while the current one has not reached the node",
      [activation("implement||a4:1", "closed", "completed")],
      [],
      2,
      "waiting",
    ],
    [
      "a failed list item over a completed one, in the current pass",
      [
        activation("implement|a|a4:2", "closed", "failed"),
        activation("implement|b|a4:2", "closed", "completed"),
      ],
      [],
      2,
      "failed",
    ],
    [
      "a completed item over a skipped one",
      [
        activation("implement|a|", "closed", "skipped"),
        activation("implement|b|", "closed", "completed"),
      ],
      [],
      null,
      "completed",
    ],
    [
      "evaluating over waiting",
      [activation("implement|a|", "ready"), activation("implement|b|", "evaluating")],
      [],
      null,
      "evaluating",
    ],
    [
      "any closing slot over the rest",
      [activation("implement|a|", "evaluating"), activation("implement|b|", "running")],
      [slot("implement|b|:0", "closing")],
      null,
      "closing",
    ],
    [
      "a closing slot of an earlier pass, which no longer counts",
      [
        activation("implement||a4:1", "closed", "completed"),
        activation("implement||a4:2", "running"),
      ],
      [slot("implement||a4:1:0", "closing")],
      2,
      "running",
    ],
  ])("folds a node's current activations: %s", (_name, activations, slots, loopPass, expected) => {
    // WHY: a node shows its most urgent state in the current pass (over its list items);
    // what an earlier pass did never shows while a later one is under way.
    const counters =
      loopPass === null
        ? []
        : [{ back_arrow_id: "a4", item_path: [], iteration_path: [], pass_index: loopPass }];
    const entry = of(
      runOverlay(CONTRACT_GRAPH, view({ activations, slots, loop_pass_indexes: counters })),
      "implement",
    );
    expect(entry.state).toBe(expected);
    // The counts still span every pass.
    expect(entry.activations).toBe(activations.length);
    expect(entry.closed).toBe(activations.filter((item) => item.status === "closed").length);
  });

  it.each<[RunView["status"], ActivationView, NodeOverlay["state"]]>([
    ["running", activation("implement||a4:1", "closed", "completed"), "waiting"],
    ["paused", activation("implement||a4:1", "closed", "failed"), "waiting"],
    ["completed", activation("implement||a4:1", "closed", "completed"), "completed"],
    ["failed", activation("implement||a4:1", "closed", "failed"), "failed"],
    ["cancelled", activation("implement||a4:1", "closed", "skipped"), "skipped"],
    ["cancelled", activation("implement||a4:1", "waiting_join"), "idle"],
  ])(
    "reads a node the last pass did not reach, in a %s run, from its %j as %s",
    (status, earlier, expected) => {
      // WHY: an ended run never reaches the node again, so "Waiting" would be wrong; it
      // shows how the node last closed, or nothing.
      const counters = [{ back_arrow_id: "a4", item_path: [], iteration_path: [], pass_index: 2 }];
      const overlay = runOverlay(
        CONTRACT_GRAPH,
        view({
          status,
          // Pass 2 took another way through the loop and never reached `implement`.
          activations: [earlier, activation("approve_change||a4:2", "closed", "completed")],
          loop_pass_indexes: counters,
        }),
      );
      expect(of(overlay, "implement")).toMatchObject({
        state: expected,
        activations: 1,
        pass: { index: 2, limit: 2 },
      });
    },
  );

  it("shows a node's latest closed outcome when the run ended past it", () => {
    // WHY: two earlier passes closed differently; the later one is how the node last ended.
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({
        status: "completed",
        activations: [
          activation("implement||a4:1", "closed", "failed"),
          activation("implement||a4:2", "closed", "completed"),
        ],
        loop_pass_indexes: [
          { back_arrow_id: "a4", item_path: [], iteration_path: [], pass_index: 3 },
        ],
      }),
    );
    expect(of(overlay, "implement").state).toBe("completed");
  });

  it("reads the recorded gate as waiting once pass 2 starts, until pass 2 reaches it", () => {
    // WHY: pass 1's answer is not pass 2's; the gate is the owner's again only when reached.
    const at = (seq: number) => runOverlay(CONTRACT_GRAPH, viewAt(seq));
    const marks = CONTRACT_LIVE_MARKS;
    expect(of(at(marks.gate1_open), "approve_change")).toMatchObject({
      state: "running",
      gateOpen: true,
    });
    for (const seq of [marks.gate1_answered, marks.pass2_running]) {
      expect(of(at(seq), "approve_change")).toMatchObject({
        state: "waiting",
        gateOpen: false,
        activations: 1,
        closed: 1,
        pass: { index: 2, limit: 2 },
      });
      expect(of(at(seq), "implement")).toMatchObject({ state: "running", activations: 2 });
    }
    expect(of(at(marks.gate2_open), "approve_change")).toMatchObject({
      state: "running",
      gateOpen: true,
      activations: 2,
    });
    expect(of(at(marks.finished), "approve_change").state).toBe("completed");
  });

  it("folds a run's full activation budget at one node, with a gate open per item", () => {
    // WHY: a run may hold 1,000 activations (MAX_RUN_ACTIVATIONS); a looped list puts them on one node.
    const activations: ActivationView[] = [];
    const slots: SlotView[] = [];
    for (let pass = 1; pass <= 10; pass += 1) {
      for (let item = 0; item < 100; item += 1) {
        const id = `implement|item-${item}|a4:${pass}`;
        const latest = pass === 10;
        activations.push(
          latest && item === 7
            ? activation(id, "evaluating")
            : activation(id, "closed", item % 10 === 0 ? "failed" : "completed"),
        );
        slots.push(slot(`${id}:0`, latest && item === 3 ? "working" : "closed"));
      }
    }
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({
        activations: [
          ...activations,
          activation("approve_change|item-1|a4:10", "running"),
          activation("approve_change|item-2|a4:10", "running"),
        ],
        slots,
        open_gates: ["approve_change|item-1|a4:10:1", "approve_change|item-2|a4:10:2"],
      }),
    );
    expect(of(overlay, "implement")).toMatchObject({
      state: "evaluating",
      activations: 1_000,
      closed: 999,
      gateOpen: false,
    });
    expect(of(overlay, "approve_change")).toMatchObject({
      state: "running",
      activations: 2,
      gateOpen: true,
    });
    expect(nodeStatusText(of(overlay, "approve_change"))).toBe("Waiting for you");
  });

  it("marks the gate whose visit is open, and only it", () => {
    // WHY: an open gate is what the run waits on the owner for.
    const overlay = runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS1.view);
    expect([...overlay].filter(([, entry]) => entry.gateOpen).map(([id]) => id)).toEqual([
      "approve_change",
    ]);
    expect(nodeStatusText(of(overlay, "approve_change"))).toBe("Waiting for you");
    expect(of(overlay, "implement")).toMatchObject({
      state: "completed",
      activations: 1,
      closed: 1,
    });
  });

  it("marks a step someone typed into and a step whose session changed", () => {
    // WHY: both stall the run until the owner looks, so the node says so.
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({
        activations: [activation("implement||a4:1", "running")],
        slots: [
          slot("implement||a4:1:0", "working", { pending_input: true }),
          slot("approve_change||a4:1:0", "working", { drift: true }),
        ],
      }),
    );
    expect(of(overlay, "implement")).toMatchObject({ pendingInput: true, drift: false });
    expect(of(overlay, "approve_change")).toMatchObject({ pendingInput: false, drift: true });
  });

  it("marks a node with an open decision and attaches each cause to the node it names", () => {
    // WHY: a stall names its step by node, slot or activation id; the step list shows it there.
    const causes: PauseCause[] = [
      { reason: "budget", detail: "activation_cap", subject: "implement" },
      { reason: "drift", detail: "pending_input", subject: "implement||a4:2:0" },
      { reason: "failure_path", detail: "blocked", subject: "approve_change||a4:2" },
      { reason: "failure_path", detail: "attempts_exhausted", subject: "pytest -q" },
      { reason: "user", detail: "user", subject: "" },
    ];
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({ status: "paused", causes, open_decisions: ["approve_change||a4:2"] }),
    );
    expect(of(overlay, "implement").causes).toEqual([causes[0], causes[1]]);
    expect(of(overlay, "approve_change").causes).toEqual([causes[2]]);
    expect(of(overlay, "approve_change").decisionOpen).toBe(true);
    expect(of(overlay, "implement").decisionOpen).toBe(false);
    expect([...overlay.values()].flatMap((entry) => entry.causes)).toHaveLength(3);
  });

  it("counts the loop's pass on every node of its body, as pass N of M", () => {
    // WHY: the loop counter tells how many tries the run has left at that loop.
    const pass1 = runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS1.view);
    const pass2 = runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS2.view);
    expect(of(pass1, "implement").pass).toEqual({ index: 1, limit: 2 });
    expect(of(pass2, "implement").pass).toEqual({ index: 2, limit: 2 });
    expect(of(pass2, "approve_change").pass).toEqual({ index: 2, limit: 2 });
    expect(of(pass2, "start").pass).toBeNull();
    expect(of(pass2, "end").pass).toBeNull();
    expect(passText(of(pass2, "implement").pass!)).toBe("pass 2 of 2");
    expect(of(pass2, "implement")).toMatchObject({ activations: 2, closed: 2, state: "completed" });
  });

  describe("in two nested loops", () => {
    // plan → code ⇄ test (inner `i1`, 3 passes) → review → back to plan (outer `o1`, 2 passes).
    const base = CONTRACT_GRAPH.nodes.find((candidate) => candidate.id === "implement")!;
    const step = (id: string) => ({ ...base, id, name: id, evidence: null });
    const loop = (
      backArrowId: string,
      head: string,
      tail: string,
      body: string[],
      limit: number | null,
    ) => ({
      back_arrow_id: backArrowId,
      head,
      tail,
      body,
      limit,
      at_limit_arrow_id: null,
      entry_arrow_ids: [],
    });
    const NESTED: CompiledGraph = {
      ...CONTRACT_GRAPH,
      nodes: ["plan", "code", "test", "review"].map(step),
      arrows: [],
      analysis: {
        ...CONTRACT_GRAPH.analysis,
        // Inner first: the order the analysis lists loops in does not decide nesting.
        loops: [
          loop("i1", "code", "test", ["code", "test"], 3),
          loop("o1", "plan", "review", ["plan", "code", "test", "review"], 2),
        ],
      },
    };
    const counter = (backArrowId: string, iterationPath: string[], passIndex: number) => ({
      back_arrow_id: backArrowId,
      item_path: [],
      iteration_path: iterationPath,
      pass_index: passIndex,
    });
    const done = (id: string) => activation(id, "closed", "completed");
    // Outer pass 1 ran the inner loop to its third pass; outer pass 2 has just planned.
    const OUTER_PASS_1 = [
      done("plan||o1:1"),
      ...[1, 2, 3].flatMap((inner) => [
        done(`code||o1:1/i1:${inner}`),
        done(`test||o1:1/i1:${inner}`),
      ]),
      done("review||o1:1"),
      done("plan||o1:2"),
    ];
    const COUNTERS = [counter("o1", [], 2), counter("i1", ["o1:1"], 3)];

    it("takes the inner loop's counter of the outer pass the node is in", () => {
      // WHY: the inner loop restarts in each outer pass; its pass 3 of outer pass 1 is history.
      const overlay = runOverlay(
        NESTED,
        view({
          activations: [...OUTER_PASS_1, activation("code||o1:2/i1:1", "running")],
          loop_pass_indexes: [...COUNTERS, counter("i1", ["o1:2"], 1)],
        }),
      );
      expect(of(overlay, "code")).toMatchObject({
        state: "running",
        pass: { index: 1, limit: 3 },
        activations: 4,
        closed: 3,
      });
      expect(of(overlay, "test")).toMatchObject({ state: "waiting", pass: { index: 1, limit: 3 } });
      expect(of(overlay, "plan")).toMatchObject({
        state: "completed",
        pass: { index: 2, limit: 2 },
      });
      expect(of(overlay, "review")).toMatchObject({
        state: "waiting",
        pass: { index: 2, limit: 2 },
      });
    });

    it("shows no inner pass before the inner loop starts in this outer pass", () => {
      // WHY: no counter is the inner loop's yet, and an old one would name the wrong pass.
      const overlay = runOverlay(
        NESTED,
        view({ activations: OUTER_PASS_1, loop_pass_indexes: COUNTERS }),
      );
      expect(of(overlay, "code")).toMatchObject({ state: "waiting", pass: null });
      expect(of(overlay, "test")).toMatchObject({ state: "waiting", pass: null });
      expect(of(overlay, "plan").pass).toEqual({ index: 2, limit: 2 });
    });

    it("names a loop without a limit as pass N", () => {
      // WHY: an unbounded loop has no "of M".
      const unbounded: CompiledGraph = {
        ...NESTED,
        analysis: { ...NESTED.analysis, loops: [loop("o1", "plan", "review", ["plan"], null)] },
      };
      const entry = of(
        runOverlay(unbounded, view({ loop_pass_indexes: [counter("o1", [], 3)] })),
        "plan",
      );
      expect(entry.pass).toEqual({ index: 3, limit: null });
      expect(passText(entry.pass!)).toBe("pass 3");
    });
  });

  it("loops each list item on its own counter", () => {
    // WHY: inside a list, every item loops separately; one item's later pass is not another's.
    const counters = [
      { back_arrow_id: "a4", item_path: ["f1"], iteration_path: [], pass_index: 2 },
      { back_arrow_id: "a4", item_path: ["f2"], iteration_path: [], pass_index: 1 },
    ];
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({
        activations: [
          activation("implement|f1|a4:1", "closed", "failed"),
          activation("implement|f2|a4:1", "closed", "completed"),
          activation("implement|f1|a4:2", "closed", "skipped"),
        ],
        loop_pass_indexes: counters,
      }),
    );
    // f1's failed pass 1 is history; f2's pass 1 is current and completed.
    expect(of(overlay, "implement").state).toBe("completed");
  });

  it("ignores ids that name no node of the graph", () => {
    // WHY: a view from a newer engine must not invent nodes or crash the canvas.
    const overlay = runOverlay(
      CONTRACT_GRAPH,
      view({
        activations: [activation("ghost||", "running"), activation("no-bar", "running")],
        slots: [slot("ghost||:0", "closing"), slot("no-colon", "closing")],
        open_gates: ["ghost||:1"],
        open_decisions: ["ghost||"],
      }),
    );
    expect([...overlay.keys()]).toEqual(["start", "implement", "approve_change", "end"]);
    expect([...overlay.values()].every((entry) => entry.state === "idle")).toBe(true);
  });

  it("shows the finished run completed everywhere", () => {
    // WHY: the end of the run reads as done on every node it reached.
    const overlay = runOverlay(CONTRACT_GRAPH, CONTRACT_FINAL_DETAIL.view);
    expect([...overlay.values()].map((entry) => entry.state)).toEqual([
      "completed",
      "completed",
      "completed",
      "completed",
    ]);
    expect([...overlay.values()].some((entry) => entry.gateOpen)).toBe(false);
  });

  it.each<[NodeOverlay["state"], string]>([
    ["idle", "Not started"],
    ["waiting", "Waiting"],
    ["running", "Running"],
    ["evaluating", "Checking evidence…"],
    ["closing", "Committing"],
    ["completed", "Completed"],
    ["failed", "Failed"],
    ["skipped", "Skipped"],
  ])("says %s as %s", (state, text) => {
    // WHY: the canvas and the step list say one state the same way.
    const entry = of(runOverlay(CONTRACT_GRAPH, null), "implement");
    expect(nodeStatusText({ ...entry, state })).toBe(text);
  });
});

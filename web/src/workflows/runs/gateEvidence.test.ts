import { describe, expect, it } from "vitest";
import type { CompiledGraph, CompiledNode, RunView } from "../api/generated/coralApi";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_GRAPH,
} from "../fixtures/runViewContract";
import { gateEvidence } from "./gateEvidence";

const PASS1 = CONTRACT_DETAIL_GATE_PASS1.view!;

function withNodes(extra: CompiledNode[], arrows: CompiledGraph["arrows"]): CompiledGraph {
  return {
    ...CONTRACT_GRAPH,
    nodes: [...CONTRACT_GRAPH.nodes, ...extra],
    arrows: [...CONTRACT_GRAPH.arrows, ...arrows],
  };
}

const implementNode = CONTRACT_GRAPH.nodes.find((node) => node.id === "implement")!;
const arrow = (id: string, source: string, target: string) => ({
  id,
  source,
  target,
  label: null,
  kind: "forward" as const,
  limit: null,
  at_limit: null,
});

describe("gateEvidence", () => {
  it("lists the checks of the step that led to the gate, met when its handoff was accepted", () => {
    // WHY: the owner sees what Coral checked before the change reached them.
    expect(gateEvidence(CONTRACT_GRAPH, PASS1, "approve_change")).toEqual([
      { nodeId: "implement", label: "Implement", commands: ["pytest -q"], met: true },
    ]);
    expect(gateEvidence(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS2.view, "approve_change")).toEqual(
      [{ nodeId: "implement", label: "Implement", commands: ["pytest -q"], met: true }],
    );
  });

  it.each<[string, RunView | null]>([
    ["before the view arrives", null],
    [
      "while the step's latest pass still works",
      {
        ...PASS1,
        activations: [
          ...PASS1.activations,
          { id: "implement||a4:2", status: "running", outcome: null },
        ],
      },
    ],
    [
      "when its latest pass failed",
      {
        ...PASS1,
        activations: PASS1.activations.map((item) =>
          item.id === "implement||a4:1" ? { ...item, outcome: "failed" as const } : item,
        ),
      },
    ],
    ["when the step never ran", { ...PASS1, activations: [] }],
  ])("says not checked yet %s", (_name, view) => {
    // WHY: only an accepted handoff passed the check; anything else has not been checked.
    expect(gateEvidence(CONTRACT_GRAPH, view, "approve_change")).toEqual([
      { nodeId: "implement", label: "Implement", commands: ["pytest -q"], met: false },
    ]);
  });

  it("lists nothing for a gate no evidence-checked step leads to", () => {
    // WHY: the start node and a step without checks have nothing to show.
    const graph = withNodes(
      [
        { ...implementNode, id: "review", name: null, evidence: null },
        {
          ...implementNode,
          id: "lint",
          name: "Lint",
          evidence: { ...implementNode.evidence!, items: [] },
        },
      ],
      [arrow("x1", "start", "end"), arrow("x2", "review", "end"), arrow("x3", "lint", "end")],
    );
    expect(gateEvidence(graph, PASS1, "end")).toEqual([]);
    expect(gateEvidence(graph, PASS1, "missing")).toEqual([]);
  });

  it("lists each step and command once, in arrow order, named by id without a name", () => {
    // WHY: two arrows from one step are one step's checks; a nameless step still reads.
    const graph = withNodes(
      [
        {
          ...implementNode,
          id: "tests",
          name: " ",
          evidence: {
            ...implementNode.evidence!,
            items: [
              { item_id: "t1", run: "pytest -q tests/unit", may_modify: false, allow_args: false },
              { item_id: "t2", run: "ruff check", may_modify: false, allow_args: false },
              { item_id: "t3", run: "ruff check", may_modify: false, allow_args: false },
            ],
          },
        },
      ],
      [arrow("x1", "tests", "approve_change"), arrow("x2", "implement", "approve_change")],
    );
    expect(gateEvidence(graph, PASS1, "approve_change")).toEqual([
      { nodeId: "implement", label: "Implement", commands: ["pytest -q"], met: true },
      {
        nodeId: "tests",
        label: "tests",
        commands: ["pytest -q tests/unit", "ruff check"],
        met: false,
      },
    ]);
  });
});

import { describe, expect, it } from "vitest";
import {
  activationNodeId,
  iterationSegment,
  parseActivationId,
  slotActivationId,
  slotNodeId,
} from "./runIds";

describe("activationNodeId", () => {
  it.each<[string, string | null]>([
    ["choose||", "choose"],
    ["review|items/0|1", "review"],
    ["choose", null],
    ["|x|", null],
    ["", null],
  ])("reads the node of activation %j", (activationId, nodeId) => {
    // WHY: open decisions are activation ids, and the banner names their node.
    expect(activationNodeId(activationId)).toBe(nodeId);
  });
});

describe("slotNodeId", () => {
  it.each<[string, string | null]>([
    ["implement||a4:2:0", "implement"],
    ["review|items/0|:1", "review"],
    ["implement||a4:2", "implement"],
    ["implement:0", null],
    ["", null],
    [":0", null],
    ["|x|:0", null],
  ])("reads the node of slot %j", (slotId, nodeId) => {
    // WHY: a slot is `<activation>:<index>` and an activation `<node>|<item>|<iteration>`.
    expect(slotNodeId(slotId)).toBe(nodeId);
  });
});

describe("parseActivationId", () => {
  it.each<[string, ReturnType<typeof parseActivationId>]>([
    ["start||", { nodeId: "start", itemPath: "", iterationPath: [] }],
    ["implement||a4:2", { nodeId: "implement", itemPath: "", iterationPath: ["a4:2"] }],
    [
      "code|files/a.py|outer:2/inner:1",
      { nodeId: "code", itemPath: "files/a.py", iterationPath: ["outer:2", "inner:1"] },
    ],
    ["review|a|b|o:1", { nodeId: "review", itemPath: "a|b", iterationPath: ["o:1"] }],
    ["review|items", { nodeId: "review", itemPath: "items", iterationPath: [] }],
    ["choose", null],
    ["|x|", null],
  ])("reads %j", (activationId, parts) => {
    // WHY: a node's current pass is read from its activations' iteration paths.
    expect(parseActivationId(activationId)).toEqual(parts);
  });
});

describe("iterationSegment", () => {
  it.each<[string, ReturnType<typeof iterationSegment>]>([
    ["a4:2", { backArrowId: "a4", pass: 2 }],
    ["loop:back:10", { backArrowId: "loop:back", pass: 10 }],
    ["a4:0", null],
    ["a4:x", null],
    ["a4:1.5", null],
    [":2", null],
    ["a4", null],
  ])("reads %j", (segment, parsed) => {
    // WHY: a malformed segment from a newer engine must not count as a pass.
    expect(iterationSegment(segment)).toEqual(parsed);
  });
});

describe("slotActivationId", () => {
  it.each<[string, string | null]>([
    ["implement||a4:2:0", "implement||a4:2"],
    ["implement||:1", "implement||"],
    ["no-colon", null],
  ])("reads the activation of slot %j", (slotId, activationId) => {
    // WHY: a slot's state counts only while its activation is in the current pass.
    expect(slotActivationId(slotId)).toBe(activationId);
  });
});

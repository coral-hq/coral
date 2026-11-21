import { describe, expect, it } from "vitest";
import { harnessLabel } from "./harnessLabel";

describe("harnessLabel", () => {
  it.each<[string | null, string | null]>([
    ["claude-sdk", "Claude"],
    ["claude-native", "Claude Code"],
    ["codex", "Codex"],
    ["cursor", "Cursor"],
    ["a-future-harness", "a-future-harness"],
    ["", null],
    [null, null],
  ])("names %j as %j", (harness, label) => {
    // WHY: a step's chip names the agent the way people know it; an unknown id stays readable.
    expect(harnessLabel(harness)).toBe(label);
  });

  it("does not read a prototype member as a label", () => {
    // WHY: the harness comes from the workflow's YAML, so any string can arrive.
    expect(harnessLabel("constructor")).toBe("constructor");
    expect(harnessLabel("toString")).toBe("toString");
  });
});

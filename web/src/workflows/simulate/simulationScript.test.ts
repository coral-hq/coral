import { describe, expect, it } from "vitest";
import { scriptFromAnswers } from "./simulationScript";

describe("scriptFromAnswers", () => {
  it("sends an empty script before any answer", () => {
    expect(scriptFromAnswers([])).toEqual({ inputs: [] });
  });

  it("groups answers by node and kind, keeping the order they were given in", () => {
    // WHY: the server reads each node's values for one kind of question first to last.
    expect(
      scriptFromAnswers([
        { nodeId: "review", kind: "label", value: "changes_requested" },
        { nodeId: "implement", kind: "done_when", value: "fail" },
        { nodeId: "review", kind: "label", value: "approved" },
        { nodeId: "implement", kind: "done_when", value: "pass" },
        { nodeId: "implement", kind: "label", value: "done" },
        { nodeId: "approve_change", kind: "gate", value: "approve" },
      ]),
    ).toEqual({
      inputs: [
        { node_id: "review", kind: "label", values: ["changes_requested", "approved"] },
        { node_id: "implement", kind: "done_when", values: ["fail", "pass"] },
        { node_id: "implement", kind: "label", values: ["done"] },
        { node_id: "approve_change", kind: "gate", values: ["approve"] },
      ],
    });
  });
});

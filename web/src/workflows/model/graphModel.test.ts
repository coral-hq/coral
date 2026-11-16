import { describe, expect, it } from "vitest";
import { MINIMAL_COMPILED, PR_REVIEW_COMPILED } from "../fixtures";
import { FLOW_NODE_TYPE, fromCompiledGraph } from "./graphModel";

describe("fromCompiledGraph", () => {
  it("maps every node and arrow of a compiled graph", () => {
    const { nodes, edges } = fromCompiledGraph(PR_REVIEW_COMPILED);
    expect(nodes).toHaveLength(PR_REVIEW_COMPILED.nodes.length);
    expect(edges).toHaveLength(PR_REVIEW_COMPILED.arrows.length);
    expect(nodes.every((node) => node.type === FLOW_NODE_TYPE)).toBe(true);
  });

  it("labels nodes by name, falling back to id, and carries the goal as detail", () => {
    const { nodes } = fromCompiledGraph(MINIMAL_COMPILED);
    const byId = Object.fromEntries(nodes.map((node) => [node.id, node]));
    expect(byId.start.data.label).toBe("start");
    expect(byId.work.data).toMatchObject({
      label: "Work",
      detail: "Do the thing",
      nodeKind: "step",
      roster: ["implementer"],
    });
  });

  it("keeps arrow labels and kinds, including back arrows", () => {
    const { edges } = fromCompiledGraph(PR_REVIEW_COMPILED);
    const back = edges.find((edge) => edge.data.arrowKind === "back");
    expect(back).toMatchObject({ source: "fix", target: "review", label: "revise" });
    expect(edges.find((edge) => edge.id === "a1")).not.toHaveProperty("label");
  });

  it("drops arrows that reference missing nodes", () => {
    const broken = {
      ...MINIMAL_COMPILED,
      arrows: [
        ...MINIMAL_COMPILED.arrows,
        { id: "ghost", source: "work", target: "nowhere", kind: "forward" as const },
      ],
    };
    expect(fromCompiledGraph(broken).edges.map((edge) => edge.id)).toEqual(["a1", "a2"]);
  });
});

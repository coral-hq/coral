import { describe, expect, it } from "vitest";
import { PR_REVIEW_COMPILED } from "../fixtures";
import { fromCompiledGraph } from "../model/graphModel";
import { layoutGraph } from "./dagreLayout";

describe("layoutGraph", () => {
  const graph = fromCompiledGraph(PR_REVIEW_COMPILED);
  const laidOut = layoutGraph(graph);
  const position = (id: string) => laidOut.nodes.find((node) => node.id === id)!.position;

  it("positions every node without moving the input", () => {
    expect(laidOut.nodes).toHaveLength(graph.nodes.length);
    expect(graph.nodes.every((node) => node.position.x === 0 && node.position.y === 0)).toBe(true);
    expect(laidOut.edges).toEqual(graph.edges);
  });

  it("flows top to bottom from start to end", () => {
    expect(position("start").y).toBeLessThan(position("find_prs").y);
    expect(position("find_prs").y).toBeLessThan(position("review").y);
    expect(position("review").y).toBeLessThan(position("end").y);
  });

  it("gives no two nodes the same spot, even with a loop", () => {
    const spots = new Set(laidOut.nodes.map(({ position: { x, y } }) => `${x},${y}`));
    expect(spots.size).toBe(laidOut.nodes.length);
  });

  it("returns an empty graph unchanged", () => {
    const empty = { nodes: [], edges: [] };
    expect(layoutGraph(empty)).toBe(empty);
  });
});

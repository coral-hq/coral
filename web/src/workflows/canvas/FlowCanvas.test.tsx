import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MINIMAL_COMPILED, PR_REVIEW_COMPILED } from "../fixtures";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_GRAPH,
} from "../fixtures/runViewContract";
import { lastFlowProps } from "../fixtures/xyflowDouble";

// xyflow needs layout APIs jsdom lacks; the double renders each custom node with its data.
vi.mock("@xyflow/react", () => import("../fixtures/xyflowDouble"));
vi.mock("@xyflow/react/dist/style.css", () => ({}));

import { FlowCanvas } from "./FlowCanvas";
import { runOverlay } from "./runOverlay";

const node = (nodeId: string) =>
  within(
    screen.getAllByTestId("rf-node").find((element) => element.dataset.id === nodeId)!,
  ).getByTestId("flow-node");

describe("FlowCanvas", () => {
  it("renders one node per compiled node and tracks graph changes", () => {
    const { rerender } = render(<FlowCanvas compiled={MINIMAL_COMPILED} />);
    expect(screen.getAllByTestId("rf-node")).toHaveLength(3);
    expect(screen.getByTestId("flow-canvas")).toHaveAttribute("data-node-count", "3");

    rerender(<FlowCanvas compiled={PR_REVIEW_COMPILED} />);
    expect(screen.getAllByTestId("rf-node")).toHaveLength(PR_REVIEW_COMPILED.nodes.length);
  });

  it("is read-only", () => {
    render(<FlowCanvas compiled={MINIMAL_COMPILED} />);
    expect(lastFlowProps.current).toMatchObject({
      nodesDraggable: false,
      nodesConnectable: false,
      elementsSelectable: false,
    });
  });

  it("renders an empty canvas without a graph", () => {
    render(<FlowCanvas compiled={null} />);
    expect(screen.queryAllByTestId("rf-node")).toHaveLength(0);
  });

  it("draws the editor's nodes with their goal and no run state or selection", () => {
    // WHY: without the run props the editor's canvas is unchanged.
    render(<FlowCanvas compiled={CONTRACT_GRAPH} />);
    const implement = node("implement");
    expect(implement).toHaveTextContent("Implement");
    expect(implement).toHaveTextContent("Implement the change");
    expect(implement).not.toHaveAttribute("data-state");
    expect(implement).not.toHaveAttribute("data-selected");
    expect(within(implement).queryByRole("img", { name: "Evidence checks" })).toBeNull();
    expect(lastFlowProps.current.onNodeClick).toBeUndefined();
  });

  it("draws each node's run state, loop counter, evidence shield, open gate and selection", () => {
    // WHY: the canvas shows where the run is at a glance.
    const overlay = runOverlay(CONTRACT_GRAPH, {
      ...CONTRACT_DETAIL_GATE_PASS2.view!,
      slots: [{ id: "implement||a4:2:0", status: "closed", pending_input: true, drift: false }],
    });
    render(<FlowCanvas compiled={CONTRACT_GRAPH} overlay={overlay} selectedNodeId="implement" />);
    const implement = node("implement");
    expect(implement).toHaveAttribute("data-state", "completed");
    expect(implement).toHaveAttribute("data-selected", "true");
    expect(within(implement).getByTestId("flow-node-status")).toHaveTextContent(
      "Completed · pass 2 of 2",
    );
    expect(within(implement).getByRole("img", { name: "Evidence checks" })).toBeInTheDocument();
    expect(within(implement).getByRole("img", { name: "Needs attention" })).toBeInTheDocument();
    expect(implement).not.toHaveTextContent("Implement the change");

    const gate = node("approve_change");
    expect(gate).toHaveAttribute("data-state", "running");
    expect(gate).toHaveAttribute("data-gate-open", "true");
    expect(gate.className).toContain("motion-safe:animate-pulse");
    expect(within(gate).getByTestId("flow-node-status")).toHaveTextContent(
      "Waiting for you · pass 2 of 2",
    );
    expect(gate).not.toHaveAttribute("data-selected");
    expect(node("end")).toHaveAttribute("data-state", "idle");
  });

  it("keeps xyflow's node objects across run updates and selection", () => {
    // WHY: new node objects make xyflow re-measure every node and drop its edges until then.
    const { rerender } = render(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS1.view)}
        selectedNodeId={null}
        onSelectNode={() => {}}
      />,
    );
    const nodes = lastFlowProps.current.nodes;
    const onNodeClick = lastFlowProps.current.onNodeClick;
    const onSelectNode = () => {};
    rerender(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS2.view)}
        selectedNodeId="implement"
        onSelectNode={onSelectNode}
      />,
    );
    expect(lastFlowProps.current.nodes).toBe(nodes);
    expect(node("implement")).toHaveAttribute("data-selected", "true");
    expect(within(node("implement")).getByTestId("flow-node-status")).toHaveTextContent(
      "Completed · pass 2 of 2",
    );
    rerender(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS2.view)}
        selectedNodeId="implement"
        onSelectNode={onSelectNode}
      />,
    );
    expect(lastFlowProps.current.nodes).toBe(nodes);
    // The click handler changes only with the page's own.
    const kept = lastFlowProps.current.onNodeClick;
    expect(kept).not.toBe(onNodeClick);
    rerender(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={null}
        selectedNodeId="implement"
        onSelectNode={onSelectNode}
      />,
    );
    expect(lastFlowProps.current.onNodeClick).toBe(kept);
  });

  it("makes no node or edge a tab stop when nodes select, and shows they can be clicked", () => {
    // WHY: xyflow's nodes would be keyboard stops that do nothing; the step list is the keyboard path.
    render(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={runOverlay(CONTRACT_GRAPH, null)}
        selectedNodeId={null}
        onSelectNode={() => {}}
      />,
    );
    expect(lastFlowProps.current).toMatchObject({ nodesFocusable: false, edgesFocusable: false });
    expect(node("implement").className).toContain("cursor-pointer");
  });

  it("leaves the editor's focus and cursor as xyflow sets them", () => {
    // WHY: the editor's canvas is unchanged by the run view.
    render(<FlowCanvas compiled={CONTRACT_GRAPH} />);
    expect(lastFlowProps.current).not.toHaveProperty("nodesFocusable");
    expect(lastFlowProps.current).not.toHaveProperty("edgesFocusable");
    expect(node("implement").className).not.toContain("cursor-pointer");
  });

  it("marks a node with an open decision, as the step list does", () => {
    // WHY: the canvas and the list say the same about a step waiting on the orchestrator.
    const overlay = runOverlay(CONTRACT_GRAPH, {
      ...CONTRACT_DETAIL_GATE_PASS1.view!,
      open_decisions: ["approve_change||a4:1"],
    });
    render(<FlowCanvas compiled={CONTRACT_GRAPH} overlay={overlay} />);
    expect(
      within(node("approve_change")).getByRole("img", { name: "Waiting for the orchestrator" }),
    ).toBeInTheDocument();
    expect(
      within(node("implement")).queryByRole("img", { name: "Waiting for the orchestrator" }),
    ).toBeNull();
  });

  it("selects the node that was clicked", () => {
    // WHY: a node click opens that step's details beside the canvas.
    const onSelectNode = vi.fn();
    render(
      <FlowCanvas
        compiled={CONTRACT_GRAPH}
        overlay={runOverlay(CONTRACT_GRAPH, null)}
        selectedNodeId={null}
        onSelectNode={onSelectNode}
      />,
    );
    fireEvent.click(node("approve_change"));
    expect(onSelectNode).toHaveBeenCalledWith("approve_change");
  });
});

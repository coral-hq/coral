import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { MINIMAL_COMPILED, PR_REVIEW_COMPILED } from "../fixtures";

// xyflow needs layout APIs jsdom lacks; render its inputs as plain DOM.
const flowProps = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));
vi.mock("@xyflow/react", () => ({
  ReactFlow: (props: { nodes: { id: string }[]; children?: React.ReactNode }) => {
    flowProps.current = props as unknown as Record<string, unknown>;
    return (
      <div>
        {props.nodes.map((node) => (
          <span key={node.id} data-testid="rf-node" />
        ))}
        {props.children}
      </div>
    );
  },
  Background: () => null,
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom" },
}));
vi.mock("@xyflow/react/dist/style.css", () => ({}));

import { FlowCanvas } from "./FlowCanvas";

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
    expect(flowProps.current).toMatchObject({
      nodesDraggable: false,
      nodesConnectable: false,
      elementsSelectable: false,
    });
  });

  it("renders an empty canvas without a graph", () => {
    render(<FlowCanvas compiled={null} />);
    expect(screen.queryAllByTestId("rf-node")).toHaveLength(0);
  });
});

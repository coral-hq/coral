import type { ComponentType, MouseEvent, ReactNode } from "react";

// A stand-in for `@xyflow/react` in jsdom, which lacks the layout APIs xyflow needs. It
// renders each node through its custom node type with the node's data, and hands node
// clicks to `onNodeClick`, so tests see what the canvas draws. Load it in a test with
// `vi.mock("@xyflow/react", () => import("../fixtures/xyflowDouble"))`.

interface DoubleNode {
  id: string;
  type?: string;
  data: Record<string, unknown>;
}

type DoubleNodeType = ComponentType<{ id: string; type?: string; data: Record<string, unknown> }>;

interface DoubleFlowProps {
  nodes: DoubleNode[];
  nodeTypes?: Record<string, DoubleNodeType>;
  onNodeClick?: (event: MouseEvent, node: DoubleNode) => void;
  children?: ReactNode;
}

/** The props of the last `ReactFlow` rendered. */
export const lastFlowProps: { current: Record<string, unknown> } = { current: {} };

export function ReactFlow(props: DoubleFlowProps) {
  lastFlowProps.current = props as unknown as Record<string, unknown>;
  const { nodes, nodeTypes, onNodeClick, children } = props;
  return (
    <div data-testid="rf-pane">
      {nodes.map((node) => {
        const NodeType = node.type === undefined ? undefined : nodeTypes?.[node.type];
        return (
          <div
            key={node.id}
            data-testid="rf-node"
            data-id={node.id}
            onClick={onNodeClick ? (event) => onNodeClick(event, node) : undefined}
          >
            {NodeType && <NodeType id={node.id} type={node.type} data={node.data} />}
          </div>
        );
      })}
      {children}
    </div>
  );
}

export const Background = () => null;
export const Handle = () => null;
export const Position = { Top: "top", Bottom: "bottom", Left: "left", Right: "right" } as const;

import { useMemo } from "react";
import { Background, Handle, Position, ReactFlow, type NodeProps, type Node } from "@xyflow/react";
import { cn } from "@/lib/utils";
import { layoutGraph } from "../layout/dagreLayout";
import { FLOW_NODE_TYPE, fromCompiledGraph, type FlowNodeData } from "../model/graphModel";
import type { CompiledGraph } from "../api/workflowTypes";

import "@xyflow/react/dist/style.css";

const KIND_STYLE: Record<FlowNodeData["nodeKind"], string> = {
  start: "rounded-full border-muted-foreground/40 bg-muted/40",
  end: "rounded-full border-muted-foreground/40 bg-muted/40",
  step: "rounded-lg border-border bg-card",
  decision: "rounded-lg border-warning/50 bg-warning/5",
  gate: "rounded-lg border-brand-accent/60 bg-brand-accent/5",
};

function WorkflowNode({ data }: NodeProps<Node<FlowNodeData>>) {
  return (
    <div
      data-testid="flow-node"
      data-node-kind={data.nodeKind}
      className={cn(
        "flex h-full w-full flex-col justify-center border px-3 py-1.5 text-center",
        KIND_STYLE[data.nodeKind],
      )}
    >
      <Handle type="target" position={Position.Top} className="!size-1.5 !border-0" />
      <span className="truncate font-medium text-foreground text-sm">{data.label}</span>
      {data.detail && <span className="truncate text-muted-foreground text-xs">{data.detail}</span>}
      <Handle type="source" position={Position.Bottom} className="!size-1.5 !border-0" />
    </div>
  );
}

const NODE_TYPES = { [FLOW_NODE_TYPE]: WorkflowNode };

/** Read-only DAG of a compiled workflow. */
export function FlowCanvas({ compiled }: { compiled: CompiledGraph | null }) {
  const graph = useMemo(
    () => (compiled ? layoutGraph(fromCompiledGraph(compiled)) : { nodes: [], edges: [] }),
    [compiled],
  );
  return (
    <div className="size-full" data-testid="flow-canvas" data-node-count={graph.nodes.length}>
      <ReactFlow
        nodes={graph.nodes}
        edges={graph.edges}
        nodeTypes={NODE_TYPES}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background />
      </ReactFlow>
    </div>
  );
}

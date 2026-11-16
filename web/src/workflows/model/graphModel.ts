import type { ArrowKind, CompiledGraph, NodeKind } from "../api/workflowTypes";

export const FLOW_NODE_TYPE = "workflowNode";

export interface FlowNodeData extends Record<string, unknown> {
  nodeKind: NodeKind;
  label: string;
  detail: string | null;
  roster: string[];
}

/** Structurally compatible with xyflow's Node; kept free of xyflow so only `canvas/` imports it. */
export interface FlowNodeModel {
  id: string;
  type: typeof FLOW_NODE_TYPE;
  position: { x: number; y: number };
  width: number;
  height: number;
  data: FlowNodeData;
}

export interface FlowEdgeModel {
  id: string;
  source: string;
  target: string;
  label?: string;
  data: { arrowKind: ArrowKind };
}

export interface FlowGraphModel {
  nodes: FlowNodeModel[];
  edges: FlowEdgeModel[];
}

const NODE_SIZES: Record<NodeKind, { width: number; height: number }> = {
  start: { width: 120, height: 40 },
  end: { width: 120, height: 40 },
  step: { width: 220, height: 72 },
  decision: { width: 220, height: 72 },
  gate: { width: 220, height: 72 },
};

function nodeDetail(node: CompiledGraph["nodes"][number]): string | null {
  return node.goal ?? node.question ?? node.prompt ?? null;
}

/** Compiled IR to unpositioned flow nodes and edges; run `layoutGraph` to place them. */
export function fromCompiledGraph(compiled: CompiledGraph): FlowGraphModel {
  const nodeIds = new Set(compiled.nodes.map((node) => node.id));
  const nodes = compiled.nodes.map<FlowNodeModel>((node) => ({
    id: node.id,
    type: FLOW_NODE_TYPE,
    position: { x: 0, y: 0 },
    ...NODE_SIZES[node.kind],
    data: {
      nodeKind: node.kind,
      label: node.name ?? node.id,
      detail: nodeDetail(node),
      roster: node.roster ?? [],
    },
  }));
  // A dangling arrow would make xyflow warn and dagre invent nodes; skip it.
  const edges = compiled.arrows
    .filter((arrow) => nodeIds.has(arrow.source) && nodeIds.has(arrow.target))
    .map<FlowEdgeModel>((arrow) => ({
      id: arrow.id,
      source: arrow.source,
      target: arrow.target,
      ...(arrow.label ? { label: arrow.label } : {}),
      data: { arrowKind: arrow.kind },
    }));
  return { nodes, edges };
}

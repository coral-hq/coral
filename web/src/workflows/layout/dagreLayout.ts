import { graphlib, layout } from "@dagrejs/dagre";
import type { FlowEdgeModel, FlowGraphModel, FlowNodeModel } from "../model/graphModel";

const RANK_SEPARATION = 56;
const NODE_SEPARATION = 40;

/** Place nodes top-to-bottom; returns new nodes, leaving the input untouched. */
export function layoutGraph(graph: FlowGraphModel): FlowGraphModel {
  if (graph.nodes.length === 0) return graph;
  const dagreGraph = new graphlib.Graph({ multigraph: true });
  dagreGraph.setGraph({ rankdir: "TB", ranksep: RANK_SEPARATION, nodesep: NODE_SEPARATION });
  dagreGraph.setDefaultEdgeLabel(() => ({}));
  for (const node of graph.nodes) {
    dagreGraph.setNode(node.id, { width: node.width, height: node.height });
  }
  for (const edge of graph.edges) dagreGraph.setEdge(edge.source, edge.target, {}, edge.id);
  layout(dagreGraph);

  const nodes = graph.nodes.map<FlowNodeModel>((node) => {
    const placed = dagreGraph.node(node.id);
    // dagre reports centers; xyflow positions by top-left.
    return {
      ...node,
      position: { x: placed.x - node.width / 2, y: placed.y - node.height / 2 },
    };
  });
  const edges: FlowEdgeModel[] = graph.edges;
  return { nodes, edges };
}

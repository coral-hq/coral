import { createContext, useCallback, useContext, useMemo } from "react";
import {
  Background,
  Handle,
  Position,
  ReactFlow,
  type Node,
  type NodeMouseHandler,
  type NodeProps,
} from "@xyflow/react";
import { CircleAlertIcon, HourglassIcon, ShieldCheckIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { layoutGraph } from "../layout/dagreLayout";
import { FLOW_NODE_TYPE, fromCompiledGraph, type FlowNodeData } from "../model/graphModel";
import type { CompiledGraph } from "../api/workflowTypes";
import {
  isStalled,
  nodeStatusText,
  passText,
  type NodeOverlay,
  type NodeRunState,
} from "./runOverlay";

import "@xyflow/react/dist/style.css";

const KIND_STYLE: Record<FlowNodeData["nodeKind"], string> = {
  start: "rounded-full border-muted-foreground/40 bg-muted/40",
  end: "rounded-full border-muted-foreground/40 bg-muted/40",
  step: "rounded-lg border-border bg-card",
  decision: "rounded-lg border-warning/50 bg-warning/5",
  gate: "rounded-lg border-brand-accent/60 bg-brand-accent/5",
};

const STATE_RING: Record<NodeRunState, string> = {
  idle: "",
  waiting: "ring-2 ring-status-gray/50",
  running: "ring-2 ring-status-blue",
  evaluating: "ring-2 ring-status-blue",
  closing: "ring-2 ring-status-blue",
  completed: "ring-2 ring-status-green",
  failed: "ring-2 ring-status-red",
  skipped: "opacity-60",
};

/**
 * The run drawn over the graph. It reaches the nodes through context, so a live update
 * re-renders the node bodies while xyflow keeps the same node objects (and their
 * measurements and edges).
 */
interface RunCanvasState {
  overlay: ReadonlyMap<string, NodeOverlay> | null;
  selectedNodeId: string | null;
  selectable: boolean;
}

const RunCanvasContext = createContext<RunCanvasState>({
  overlay: null,
  selectedNodeId: null,
  selectable: false,
});

function RunMarks({ overlay }: { overlay: NodeOverlay }) {
  const stalled = isStalled(overlay);
  if (!overlay.evidence && !stalled && !overlay.decisionOpen) return null;
  return (
    <span className="absolute top-1 right-1 flex gap-0.5 text-muted-foreground">
      {overlay.evidence && (
        <ShieldCheckIcon role="img" aria-label="Evidence checks" className="size-3" />
      )}
      {overlay.decisionOpen && (
        <HourglassIcon role="img" aria-label="Waiting for the orchestrator" className="size-3" />
      )}
      {stalled && (
        <CircleAlertIcon
          role="img"
          aria-label="Needs attention"
          className="size-3 text-status-yellow"
        />
      )}
    </span>
  );
}

function WorkflowNode({ id, data }: NodeProps<Node<FlowNodeData>>) {
  const run = useContext(RunCanvasContext);
  const overlay = run.overlay?.get(id) ?? null;
  const selected = id === run.selectedNodeId;
  // A start or end node is too small for a status line; its ring says it.
  const statusLine = overlay !== null && data.nodeKind !== "start" && data.nodeKind !== "end";
  return (
    <div
      data-testid="flow-node"
      data-node-kind={data.nodeKind}
      data-state={overlay?.state}
      data-gate-open={overlay?.gateOpen || undefined}
      data-selected={selected || undefined}
      className={cn(
        "relative flex h-full w-full flex-col justify-center border px-3 py-1.5 text-center",
        KIND_STYLE[data.nodeKind],
        overlay && STATE_RING[overlay.state],
        overlay?.gateOpen && "ring-2 ring-status-yellow motion-safe:animate-pulse",
        selected && "outline-2 outline-offset-4 outline-foreground",
        run.selectable && "cursor-pointer",
      )}
    >
      <Handle type="target" position={Position.Top} className="!size-1.5 !border-0" />
      <span className="truncate font-medium text-foreground text-sm">{data.label}</span>
      {statusLine ? (
        <span data-testid="flow-node-status" className="truncate text-muted-foreground text-xs">
          {nodeStatusText(overlay)}
          {overlay.pass && ` · ${passText(overlay.pass)}`}
        </span>
      ) : (
        overlay === null &&
        data.detail && <span className="truncate text-muted-foreground text-xs">{data.detail}</span>
      )}
      {overlay && <RunMarks overlay={overlay} />}
      <Handle type="source" position={Position.Bottom} className="!size-1.5 !border-0" />
    </div>
  );
}

const NODE_TYPES = { [FLOW_NODE_TYPE]: WorkflowNode };

export interface FlowCanvasProps {
  compiled: CompiledGraph | null;
  /** Each node's run state; without it the canvas draws the bare graph, as the editor does. */
  overlay?: ReadonlyMap<string, NodeOverlay> | null;
  selectedNodeId?: string | null;
  /**
   * Called with a clicked node's id. With it, nodes and edges are not tab stops: the
   * page's step list is the keyboard path to the same selection.
   */
  onSelectNode?: (nodeId: string) => void;
}

/** Read-only DAG of a compiled workflow, with a run's state over it when one is given. */
export function FlowCanvas({ compiled, overlay, selectedNodeId, onSelectNode }: FlowCanvasProps) {
  const graph = useMemo(
    () => (compiled ? layoutGraph(fromCompiledGraph(compiled)) : { nodes: [], edges: [] }),
    [compiled],
  );
  const selectable = onSelectNode !== undefined;
  const run = useMemo<RunCanvasState>(
    () => ({ overlay: overlay ?? null, selectedNodeId: selectedNodeId ?? null, selectable }),
    [overlay, selectedNodeId, selectable],
  );
  const onNodeClick = useCallback<NodeMouseHandler>(
    (_event, node) => onSelectNode?.(node.id),
    [onSelectNode],
  );
  return (
    <div className="size-full" data-testid="flow-canvas" data-node-count={graph.nodes.length}>
      <RunCanvasContext.Provider value={run}>
        <ReactFlow
          nodes={graph.nodes}
          edges={graph.edges}
          nodeTypes={NODE_TYPES}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          {...(selectable ? { onNodeClick, nodesFocusable: false, edgesFocusable: false } : {})}
          fitView
          proOptions={{ hideAttribution: true }}
        >
          <Background />
        </ReactFlow>
      </RunCanvasContext.Provider>
    </div>
  );
}

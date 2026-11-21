import { ShieldCheckIcon } from "lucide-react";
import { useId } from "react";
import type { CompiledGraph } from "../api/generated/coralApi";
import { nodeStatusText, passText, type NodeOverlay } from "../canvas/runOverlay";
import { nodeLabel, pauseCopy, type GraphNodeNames } from "../shared/pauseCopy";
import { cn } from "@/lib/utils";

// The run's steps as a list beside the canvas, carrying the same state for anyone who does
// not see the canvas: each node in graph order, as a button that selects it, with its state,
// loop pass and evidence mark, and under it what stalls it.

export interface RunStepListProps {
  graph: CompiledGraph;
  overlay: ReadonlyMap<string, NodeOverlay>;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}

/** What stalls a step, once each: typed into, changed, a decision to make, its causes. */
export function stallLines(overlay: NodeOverlay, graph: GraphNodeNames | null): string[] {
  const lines: string[] = [];
  // A typed-into cause says the same, naming the step.
  const typedIntoCause = overlay.causes.some(
    (cause) => cause.reason === "drift" && cause.detail === "pending_input",
  );
  if (overlay.pendingInput && !typedIntoCause)
    lines.push("Someone typed into this step’s session.");
  if (overlay.drift) lines.push("This step’s session was changed outside Coral.");
  if (overlay.decisionOpen) lines.push("Waiting for the orchestrator to choose.");
  for (const cause of overlay.causes) lines.push(pauseCopy(cause.reason, cause, graph).body);
  return [...new Set(lines)];
}

export function RunStepList({ graph, overlay, selectedNodeId, onSelectNode }: RunStepListProps) {
  const headingId = useId();
  return (
    <section
      aria-labelledby={headingId}
      data-testid="run-step-list"
      className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3"
    >
      <h2 id={headingId} className="px-1 text-ui font-medium text-foreground">
        Steps
      </h2>
      <ol className="flex flex-col gap-1">
        {graph.nodes.map((node) => {
          const entry = overlay.get(node.id);
          if (!entry) return null;
          const selected = node.id === selectedNodeId;
          const stalls = stallLines(entry, graph);
          return (
            <li
              key={node.id}
              data-node-id={node.id}
              data-state={entry.state}
              data-gate-open={entry.gateOpen || undefined}
              className="flex flex-col"
            >
              <button
                type="button"
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelectNode(node.id)}
                className={cn(
                  "flex w-full flex-col items-start gap-0.5 rounded-lg px-2 py-1.5 text-left hover:bg-muted/60",
                  selected && "bg-muted",
                )}
              >
                <span className="flex w-full items-center gap-1.5">
                  <span className="min-w-0 truncate text-ui font-medium text-foreground">
                    {nodeLabel(graph, node.id) ?? node.id}
                  </span>
                  {entry.evidence && (
                    <span className="flex shrink-0 items-center text-muted-foreground">
                      <ShieldCheckIcon aria-hidden className="size-3.5" />
                      <span className="sr-only">Evidence checks</span>
                    </span>
                  )}
                </span>
                <span className="flex flex-wrap gap-x-1.5 text-sm text-muted-foreground">
                  <span
                    data-testid="run-step-status"
                    className={cn(entry.gateOpen && "font-medium text-status-yellow")}
                  >
                    {nodeStatusText(entry)}
                  </span>
                  {entry.pass && (
                    <>
                      <span aria-hidden>·</span>
                      <span data-testid="run-step-pass">{passText(entry.pass)}</span>
                    </>
                  )}
                </span>
              </button>
              {stalls.length > 0 && (
                <ul className="list-disc pr-2 pb-1 pl-7 text-sm text-muted-foreground">
                  {stalls.map((line) => (
                    <li key={line} data-testid="run-step-stall">
                      {line}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}

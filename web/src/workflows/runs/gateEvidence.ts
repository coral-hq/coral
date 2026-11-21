import type { CompiledGraph, RunView } from "../api/generated/coralApi";
import { nodeLabel } from "../shared/pauseCopy";
import { activationNodeId } from "../shared/runIds";

// What an open gate's card shows was checked before the work reached it: the evidence
// commands of each step with an arrow into the gate. A step's latest activation that closed
// completed had its handoff accepted, which only passes once its checks pass; anything else
// has not been checked yet. No API serves exit codes or times, so none are shown.

export interface GateEvidenceStep {
  nodeId: string;
  /** The step's name, or its id when it has none. */
  label: string;
  /** The commands its evidence runs, once each, in the graph's order. */
  commands: readonly string[];
  /** The step's latest activation closed completed: its checks passed at handoff. */
  met: boolean;
}

function latestActivation(view: RunView | null, nodeId: string) {
  return view?.activations.findLast((activation) => activationNodeId(activation.id) === nodeId);
}

/** The evidence-checked steps that lead into `nodeId`, once each, in arrow order. */
export function gateEvidence(
  graph: CompiledGraph,
  view: RunView | null,
  nodeId: string,
): GateEvidenceStep[] {
  const nodes = new Map(graph.nodes.map((node) => [node.id, node]));
  const steps: GateEvidenceStep[] = [];
  const seen = new Set<string>();
  for (const arrow of graph.arrows) {
    if (arrow.target !== nodeId || seen.has(arrow.source)) continue;
    seen.add(arrow.source);
    const source = nodes.get(arrow.source);
    const commands = [...new Set(source?.evidence?.items.map((item) => item.run))];
    if (source?.kind !== "step" || commands.length === 0) continue;
    const latest = latestActivation(view, source.id);
    steps.push({
      nodeId: source.id,
      label: nodeLabel(graph, source.id) ?? source.id,
      commands,
      met: latest?.status === "closed" && latest.outcome === "completed",
    });
  }
  return steps;
}

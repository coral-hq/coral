import { useId } from "react";
import type { CompiledNode, CompiledGraph } from "../api/generated/coralApi";
import { nodeStatusText, passText, type NodeOverlay } from "../canvas/runOverlay";
import { nodeLabel } from "../shared/pauseCopy";
import { RosterChip } from "../shared/RosterChip";

// The selected node beside the canvas: what kind of node it is and where it stands, what
// it asks or aims at, the commands its evidence runs, and the agents its roster names.

const KIND_TEXT: Readonly<Record<CompiledNode["kind"], string>> = {
  start: "Start",
  end: "End",
  step: "Step",
  decision: "Decision",
  gate: "Gate",
};

export interface RunNodePanelProps {
  graph: CompiledGraph;
  nodeId: string;
  overlay: NodeOverlay | null;
}

export function RunNodePanel({ graph, nodeId, overlay }: RunNodePanelProps) {
  const headingId = useId();
  const evidenceId = useId();
  const node = graph.nodes.find((candidate) => candidate.id === nodeId);
  if (!node) return null;
  const about = node.goal ?? node.question ?? node.prompt;
  const checks = node.evidence?.items ?? [];
  // A roster may name one profile twice: two agents of it.
  const seen = new Map<string, number>();
  const agents = node.roster.map((profile) => {
    const count = (seen.get(profile) ?? 0) + 1;
    seen.set(profile, count);
    return { profile, key: `${profile}#${count}` };
  });
  const state = [
    KIND_TEXT[node.kind],
    ...(overlay ? [nodeStatusText(overlay)] : []),
    ...(overlay?.pass ? [passText(overlay.pass)] : []),
  ];
  return (
    <section
      aria-labelledby={headingId}
      data-testid="run-node-panel"
      data-node-id={node.id}
      className="flex flex-col gap-2 rounded-xl border border-border bg-card p-3"
    >
      <h2 id={headingId} className="text-ui font-medium text-foreground">
        {nodeLabel(graph, node.id) ?? node.id}
      </h2>
      <p data-testid="run-node-state" className="text-sm text-muted-foreground">
        {state.join(" · ")}
      </p>
      {about && <p className="text-ui break-words whitespace-pre-wrap">{about}</p>}
      {checks.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 id={evidenceId} className="text-sm text-muted-foreground">
            Evidence checks
          </h3>
          <ul aria-labelledby={evidenceId} className="flex flex-col gap-0.5">
            {checks.map((check) => (
              <li key={check.item_id}>
                <code className="text-sm">{check.run}</code>
              </li>
            ))}
          </ul>
        </div>
      )}
      {agents.length > 0 && (
        <ul aria-label="Agents" className="flex flex-wrap gap-1.5">
          {agents.map(({ profile, key }) => (
            <li key={key}>
              <RosterChip profile={profile} harness={node.harness} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

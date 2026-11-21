import { CirclePauseIcon } from "lucide-react";
import { useId } from "react";
import type { RunView } from "../api/generated/coralApi";
import { isolated, nodeLabel, pauseCopy, type GraphNodeNames } from "../shared/pauseCopy";
import { activationNodeId, slotNodeId } from "../shared/runIds";

// A paused run's banner: why it paused (the first cause, or the run's reason), then what
// else it waits on: its other causes, steps someone typed into or whose session changed,
// and decisions the orchestrator has yet to make.

export interface PauseBannerProps {
  /** The run's pause reason, from the stream's header. */
  reason: string | null;
  /** The streamed view; `null` until it arrives. */
  view: RunView | null;
  /** The run's graph, for step names; `null` until it loads. */
  graph: GraphNodeNames | null;
}

/** A step's name for a sentence, isolated, or "a step" when the graph cannot name it. */
function stepName(graph: GraphNodeNames | null, nodeId: string | null): string {
  const name = nodeId === null ? null : nodeLabel(graph, nodeId);
  return name === null ? "a step" : isolated(name);
}

/** Everything else the paused run waits on, once each, leaving out what `body` says. */
function waitingOn(view: RunView | null, graph: GraphNodeNames | null, body: string): string[] {
  if (view === null) return [];
  const lines: string[] = [];
  // A typed-into cause already names its slot, in longer words.
  const typedIntoCauses = new Set<string>();
  for (const cause of view.causes) {
    lines.push(pauseCopy(cause.reason, cause, graph).body);
    if (cause.reason === "drift" && cause.detail === "pending_input") {
      typedIntoCauses.add(cause.subject);
    }
  }
  for (const slot of view.slots) {
    const step = stepName(graph, slotNodeId(slot.id));
    if (slot.pending_input && !typedIntoCauses.has(slot.id)) {
      lines.push(`Someone typed into ${step}’s session.`);
    }
    if (slot.drift) lines.push(`${step}’s session was changed outside Coral.`);
  }
  for (const decision of view.open_decisions) {
    const nodeId = activationNodeId(decision) ?? decision;
    const name = isolated(nodeLabel(graph, nodeId) ?? nodeId);
    lines.push(`Waiting for the orchestrator to choose at ${name}.`);
  }
  return [...new Set(lines)].filter((line) => line !== body);
}

export function PauseBanner({ reason, view, graph }: PauseBannerProps) {
  const titleId = useId();
  const copy = pauseCopy(reason, view?.causes[0] ?? null, graph);
  const lines = waitingOn(view, graph, copy.body);
  return (
    <section
      aria-labelledby={titleId}
      data-testid="run-pause-banner"
      className="flex gap-3 rounded-xl border border-status-yellow/40 bg-status-yellow/8 p-4"
    >
      <CirclePauseIcon aria-hidden className="mt-0.5 size-4 shrink-0 text-status-yellow" />
      <div className="flex min-w-0 flex-col gap-1">
        <h2 id={titleId} className="text-ui font-medium text-foreground">
          {copy.title}
        </h2>
        <p className="text-ui text-muted-foreground">{copy.body}</p>
        {lines.length > 0 && (
          <ul className="list-disc pl-5 text-ui text-muted-foreground">
            {lines.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

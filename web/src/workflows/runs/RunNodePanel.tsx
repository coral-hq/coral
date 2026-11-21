import { useId, type ReactNode } from "react";
import { Link } from "@/lib/routing";
import type { CompiledNode, CompiledGraph } from "../api/generated/coralApi";
import { nodeStatusText, passText, type NodeOverlay } from "../canvas/runOverlay";
import { runPath } from "../nav/coralPaths";
import { nodeLabel } from "../shared/pauseCopy";
import { RosterChip } from "../shared/RosterChip";
import { agentName, type StepActivationSessions, type StepSession } from "./agents/stepSessions";

// The selected node beside the canvas: what kind of node it is and where it stands, what
// it asks or aims at, the commands its evidence runs, and its agents: each session of each
// pass, latest first, opening its transcript; or the roster before any session exists.

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
  /** With `sessions`, each session's chip links to its transcript on this run. */
  runId?: string;
  /** The node's sessions by activation (`stepSessions`); the roster shows without them. */
  sessions?: readonly StepActivationSessions[];
  /** The session the drawer shows, marked on its chip. */
  openSessionId?: string | null;
}

const NO_SESSIONS: readonly StepActivationSessions[] = [];

export function RunNodePanel({
  graph,
  nodeId,
  overlay,
  runId,
  sessions = NO_SESSIONS,
  openSessionId = null,
}: RunNodePanelProps) {
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
      {runId !== undefined && sessions.length > 0 ? (
        <SessionChips
          runId={runId}
          nodeId={node.id}
          sessions={sessions}
          openSessionId={openSessionId}
        />
      ) : (
        agents.length > 0 && (
          <ul aria-label="Agents" className="flex flex-wrap gap-1.5">
            {agents.map(({ profile, key }) => (
              <li key={key}>
                <RosterChip profile={profile} harness={node.harness} />
              </li>
            ))}
          </ul>
        )
      )}
    </section>
  );
}

/** The chip that opens `sessionId`'s transcript, if the selected step shows one. */
export function findSessionChip(sessionId: string): HTMLElement | null {
  const chips = document.querySelectorAll<HTMLElement>("[data-session-chip]");
  return Array.from(chips).find((chip) => chip.dataset.sessionChip === sessionId) ?? null;
}

/** A session chip's name: what it opens, and which pass when the step loops. */
function transcriptLabel(session: StepSession): string {
  const pass = session.pass === null ? "" : `, pass ${session.pass}`;
  return `Open ${agentName(session)}’s transcript${pass}`;
}

/** A node's sessions, one row per pass (latest first), each chip opening its transcript. */
function SessionChips({
  runId,
  nodeId,
  sessions,
  openSessionId,
}: {
  runId: string;
  nodeId: string;
  sessions: readonly StepActivationSessions[];
  openSessionId: string | null;
}) {
  return (
    <div role="group" aria-label="Agents" className="flex flex-col gap-1.5">
      {sessions.map((group) => {
        const label = group.pass === null ? undefined : `Pass ${group.pass}`;
        return (
          <div key={group.activationId} className="flex flex-wrap items-center gap-1.5">
            {label && (
              <span aria-hidden className="text-sm text-muted-foreground">
                {label}
              </span>
            )}
            <ul aria-label={label} className="flex flex-wrap gap-1.5">
              {group.sessions.map((session) => {
                const chip = <RosterChip profile={agentName(session)} harness={session.harness} />;
                return (
                  <li key={session.engineSlotId}>
                    {session.sessionId === null ? (
                      chip
                    ) : (
                      <SessionChipLink
                        to={runPath(runId, { node: nodeId, agent: session.sessionId })}
                        sessionId={session.sessionId}
                        open={session.sessionId === openSessionId}
                        label={transcriptLabel(session)}
                      >
                        {chip}
                      </SessionChipLink>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        );
      })}
    </div>
  );
}

function SessionChipLink({
  to,
  sessionId,
  open,
  label,
  children,
}: {
  to: string;
  sessionId: string;
  open: boolean;
  label: string;
  children: ReactNode;
}) {
  return (
    <Link
      to={to}
      aria-label={label}
      aria-current={open ? "true" : undefined}
      data-session-chip={sessionId}
      // The open transcript's chip adds no second history entry for the same drawer.
      onClick={(event) => {
        if (open) event.preventDefault();
      }}
      componentId="workflows.run.node.open_transcript"
      className="block rounded-full hover:bg-muted aria-[current=true]:ring-2 aria-[current=true]:ring-ring"
    >
      {children}
    </Link>
  );
}

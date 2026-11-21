import { useEffect, useId, useRef, useState, type RefObject } from "react";
import { ApiError } from "@/lib/sessionsApi";
import type { CompiledGraph, GateOut, RunDetail, RunView } from "../api/generated/coralApi";
import { answerGate } from "../api/runsApi";
import { WorkflowGateCard, type RunViewGate } from "../inbox/WorkflowInboxCard";
import type { WorkflowGateEntryData } from "../inbox/workflowEntries";
import { activationNodeId } from "../shared/runIds";
import { gateEvidence, type GateEvidenceStep } from "./gateEvidence";
import { runViewCardUi } from "./gateCardUi";

// The run's open gates, answered inline. The stream's view says which visits are open, in
// its order; the detail supplies each one's context and outcomes. Each renders the Inbox's gate card,
// answering through the runs route with the visit's token, and the selected node's gate
// comes first. A request to show a gate (`?node=<gate>&panel=gate`) focuses its card once
// per navigation, and is spent if that gate is not open when the page first sees the run.
// A card that closes while it holds focus hands focus to `focusFallback`.

/** A request to show one node's gate, made once per navigation (`key`). */
export interface GateFocus {
  nodeId: string;
  key: string;
}

export interface RunGatePanelProps {
  runId: string;
  detail: RunDetail;
  /** The streamed view; `null` until it arrives. */
  view: RunView | null;
  /** The run's graph, for the checks that led to each gate; `null` until it loads. */
  graph: CompiledGraph | null;
  selectedNodeId: string | null;
  focus: GateFocus | null;
  /** Called after the server took or refused an answer, so the page reads the run again. */
  onAnswerSettled: () => void;
  /** Where focus goes when the card holding it closes; the page's run status. */
  focusFallback?: RefObject<HTMLElement | null>;
}

/** A gate as the Inbox card reads it: the visit's context as its prompt, the owner's own run. */
function gateEntry(gate: GateOut, detail: RunDetail): WorkflowGateEntryData {
  return {
    type: "gate",
    elicitationId: gate.elicitation_id,
    alert: null,
    prompt: {
      sessionId: detail.anchor_session_id,
      message: gate.context,
      outcomes: gate.outcomes,
      runId: detail.run_id,
      runTitle: detail.title,
      nodeId: gate.node_id,
      // The runs routes serve only the owner's runs.
      runOwner: null,
      openedAt: gate.opened_at,
    },
  };
}

/**
 * Each open visit's content: as the detail lists it, else as an earlier detail did. A reread
 * can drop a visit before the stream closes it (after a refusal, say); its card, and what it
 * says, stay until the stream does.
 */
function keepListed(
  previous: ReadonlyMap<string, GateOut>,
  gates: readonly GateOut[],
  openTokens: readonly string[],
): ReadonlyMap<string, GateOut> {
  const listed = new Map(gates.map((gate) => [gate.token, gate]));
  const kept = new Map<string, GateOut>();
  for (const token of openTokens) {
    const gate = listed.get(token) ?? previous.get(token);
    if (gate) kept.set(token, gate);
  }
  return kept;
}

function GateEvidence({ steps }: { steps: readonly GateEvidenceStep[] }) {
  const headingId = useId();
  if (steps.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-1">
      <h3 id={headingId} className="text-sm text-muted-foreground">
        Evidence
      </h3>
      {steps.map((step) => (
        <div key={step.nodeId} className="flex flex-col gap-0.5">
          <p className="text-sm text-muted-foreground">
            Checked at <bdi>{step.label}</bdi>
          </p>
          <ul className="flex flex-col gap-0.5 text-sm">
            {step.commands.map((command) => (
              <li key={command} data-testid="run-gate-check">
                <bdi>
                  <code>{command}</code>
                </bdi>{" "}
                · {step.met ? "Met at handoff" : "Not checked yet"}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}

export function RunGatePanel({
  runId,
  detail,
  view,
  graph,
  selectedNodeId,
  focus,
  onAnswerSettled,
  focusFallback,
}: RunGatePanelProps) {
  const cards = useRef(new Map<string, HTMLDivElement>());
  const focused = useRef<string | null>(null);
  const lostFocus = useRef(false);
  // Each open visit's last listed content, derived from the previous render's (React's
  // "state from the previous render" pattern), so the render stays pure.
  const openTokens = view?.open_gates ?? [];
  const openKey = JSON.stringify(openTokens);
  const [kept, setKept] = useState(() => ({
    gates: detail.gates,
    openKey,
    byToken: keepListed(new Map(), detail.gates, openTokens),
  }));
  let byToken = kept.byToken;
  if (kept.gates !== detail.gates || kept.openKey !== openKey) {
    byToken = keepListed(kept.byToken, detail.gates, openTokens);
    setKept({ gates: detail.gates, openKey, byToken });
  }
  const gates = openTokens
    .flatMap((token) => byToken.get(token) ?? [])
    .sort((a, b) => Number(b.node_id === selectedNodeId) - Number(a.node_id === selectedNodeId));
  const target = focus && gates.find((gate) => gate.node_id === focus.nodeId);
  const targetToken = target?.token ?? null;
  const viewKnown = view !== null;
  const targetOpen =
    focus !== null &&
    (view?.open_gates.some((token) => activationNodeId(token) === focus.nodeId) ?? false);

  useEffect(() => {
    if (focus === null || !viewKnown || focused.current === focus.key) return;
    // The linked gate is not open: a later visit, opened while the owner reads the page,
    // never takes focus.
    if (!targetOpen) {
      focused.current = focus.key;
      return;
    }
    // Open in the view, but the detail has not listed it yet.
    const element = targetToken === null ? undefined : cards.current.get(targetToken);
    if (!element) return;
    focused.current = focus.key;
    element.scrollIntoView({ block: "center" });
    element.focus({ preventScroll: true });
  }, [focus, viewKnown, targetOpen, targetToken]);

  // After every commit: a card that held focus and is gone left it on the page's body.
  useEffect(() => {
    if (!lostFocus.current) return;
    lostFocus.current = false;
    const active = document.activeElement;
    if (active === null || active === document.body) focusFallback?.current?.focus();
  });

  if (gates.length === 0) return null;
  const answer =
    (gate: GateOut): RunViewGate["answer"] =>
    async (outcome, note) => {
      let result: Awaited<ReturnType<typeof answerGate>>;
      try {
        result = await answerGate(runId, gate.node_id, {
          visit_token: gate.token,
          outcome,
          ...(note === null ? {} : { note }),
        });
      } catch (error) {
        // A refusal says the run moved on (another visit, a pause); a network failure says nothing.
        if (error instanceof ApiError) onAnswerSettled();
        throw error;
      }
      onAnswerSettled();
      return result;
    };
  return (
    <div data-testid="run-gate-panel" className="flex flex-col gap-3">
      {gates.map((gate) => (
        <div
          key={gate.token}
          ref={(element) => {
            if (element) {
              cards.current.set(gate.token, element);
              return;
            }
            // Also called between renders with the element still in place; the effect
            // above checks where focus actually is.
            if (cards.current.get(gate.token)?.contains(document.activeElement)) {
              lostFocus.current = true;
            }
            cards.current.delete(gate.token);
          }}
          tabIndex={-1}
          data-testid="run-gate"
          data-node-id={gate.node_id}
          data-token={gate.token}
          className="rounded-xl outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <WorkflowGateCard
            data={gateEntry(gate, detail)}
            at={gate.opened_at}
            viewerId={null}
            expanded
            onToggle={() => {}}
            ui={runViewCardUi}
            runView={{
              answer: answer(gate),
              evidence: graph && <GateEvidence steps={gateEvidence(graph, view, gate.node_id)} />,
            }}
          />
        </div>
      ))}
    </div>
  );
}

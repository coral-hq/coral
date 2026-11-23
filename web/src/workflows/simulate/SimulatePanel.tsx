import { useEffect, useId, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { WorkflowsApiError } from "../api/client";
import type {
  CompiledGraph,
  SimNeedsInput,
  SimRejection,
  SimResult,
} from "../api/generated/coralApi";
import { passText } from "../canvas/runOverlay";
import { UNKNOWN_PAUSE_TEXT, isolated, nodeLabel, pauseCopy } from "../shared/pauseCopy";
import { isServerBusy, type Simulation } from "./useSimulation";

// The editor's Simulate panel. Everything it shows from the workflow or the script is
// plain React text; names and values written into a sentence are bidi-isolated.

/** The control a person last used, whose request disables it until the answer lands. */
type Action = "answer" | "undo" | "reset";

type StoppedBy = NonNullable<SimResult["stopped_by"]>;

const STOPPED_BY_TEXT: Readonly<Record<StoppedBy, string>> = {
  transitions: "The simulation stopped after too many steps.",
  work: "The simulation stopped: the run grew too large to simulate.",
  step_seats: "The workflow cannot be simulated: a step has too many agents.",
  graph_seats: "The workflow cannot be simulated: its steps have too many agents in all.",
  graph_size: "The workflow cannot be simulated: it has too many nodes or arrows.",
};

const CHECK_RESULT_TEXT: Readonly<Record<string, string>> = {
  pass: "Checks pass",
  fail: "Checks fail",
};

export interface SimulatePanelProps {
  simulation: Simulation;
  onClose: () => void;
  id?: string;
}

export function SimulatePanel({ simulation, onClose, id }: SimulatePanelProps) {
  const { response, isPending, stale, answers, busy, error } = simulation;
  const sectionRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const undoRef = useRef<HTMLButtonElement>(null);
  const resetRef = useRef<HTMLButtonElement>(null);
  const lastAction = useRef<Action | null>(null);

  // The used control is disabled while its request runs, so focus waits on the heading, then
  // moves to that control again, else to the next question, else stays on the heading.
  const act = (action: Action, run: () => void) => {
    lastAction.current = action;
    headingRef.current?.focus();
    run();
  };
  useEffect(() => {
    const action = lastAction.current;
    if (action === null || isPending) return;
    lastAction.current = null;
    const own = action === "undo" ? undoRef.current : action === "reset" ? resetRef.current : null;
    const question = sectionRef.current?.querySelector<HTMLElement>("[data-question]");
    const target = own && !own.disabled ? own : (question ?? headingRef.current);
    target?.focus();
  }, [isPending]);

  return (
    <section
      ref={sectionRef}
      id={id}
      aria-label="Simulation"
      className="flex max-h-80 flex-col gap-3 overflow-auto border-border border-t px-6 py-3 text-ui"
      data-testid="simulate-panel"
    >
      <header className="flex flex-wrap items-center gap-2">
        <h2
          ref={headingRef}
          tabIndex={-1}
          className="font-medium text-foreground text-ui outline-none"
        >
          Simulation
        </h2>
        {isPending && (
          <span className="flex items-center gap-1 text-muted-foreground text-xs">
            <Spinner className="size-3" aria-hidden="true" />
            Simulating…
          </span>
        )}
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            ref={undoRef}
            componentId="coral.simulate.undo"
            disabled={isPending || stale || answers.length === 0}
            onClick={() => act("undo", simulation.undo)}
          >
            Undo
          </Button>
          <Button
            variant="outline"
            size="sm"
            ref={resetRef}
            componentId="coral.simulate.reset"
            disabled={isPending || answers.length === 0}
            onClick={() => act("reset", simulation.reset)}
          >
            Reset
          </Button>
          <Button variant="ghost" size="sm" componentId="coral.simulate.close" onClick={onClose}>
            Close
          </Button>
        </div>
      </header>
      {stale && (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground">The workflow changed since this simulation.</p>
          <Button
            variant="outline"
            size="sm"
            componentId="coral.simulate.rerun"
            disabled={!simulation.canRerun}
            onClick={simulation.rerun}
          >
            Simulate again
          </Button>
        </div>
      )}
      <div className="flex flex-col gap-3">
        {busy && (
          <p role="status" className="text-muted-foreground">
            The server is busy; trying again shortly.
          </p>
        )}
        {error && (
          <Failure error={error} hasAnswers={answers.length > 0} onRetry={simulation.rerun} />
        )}
        {response && !response.valid && (
          <div role="status">
            <Lines first="The workflow does not load." rest={[response.load_error.message]} />
          </div>
        )}
        {response?.valid && response.simulation === null && (
          <p role="status" className="text-foreground">
            Fix the workflow's errors to simulate it.
          </p>
        )}
        {response?.valid && response.simulation && (
          <Result
            result={response.simulation}
            compiled={response.compiled}
            simulation={simulation}
            onAnswer={(value) => act("answer", () => simulation.answer(value))}
          />
        )}
      </div>
    </section>
  );
}

function Failure({
  error,
  hasAnswers,
  onRetry,
}: {
  error: Error;
  hasAnswers: boolean;
  onRetry: () => void;
}) {
  // Sending the same answers again would be refused again; with none, another try is the way on.
  if (hasAnswers && error instanceof WorkflowsApiError && error.status === 422) {
    return (
      <p role="alert" className="text-destructive">
        The server refused one of the answers. Undo it or reset.
      </p>
    );
  }
  return (
    <div role="alert" className="flex flex-wrap items-center gap-2">
      <p className="text-destructive">
        {isServerBusy(error) ? "The server is busy; try again." : "Couldn't simulate the workflow."}
      </p>
      <Button variant="outline" size="sm" componentId="coral.simulate.retry" onClick={onRetry}>
        Try again
      </Button>
    </div>
  );
}

/** A sentence and its muted details. */
function Lines({ first, rest }: { first: string; rest: readonly string[] }) {
  return (
    <div className="flex flex-col gap-0.5">
      <p className="text-foreground">{first}</p>
      {rest.map((line) => (
        <p key={line} className="text-muted-foreground text-xs">
          {line}
        </p>
      ))}
    </div>
  );
}

interface ResultProps {
  result: SimResult;
  compiled: CompiledGraph;
  simulation: Simulation;
  onAnswer: (value: string) => void;
}

function Result({ result, compiled, simulation, onAnswer }: ResultProps) {
  const name = (nodeId: string) => isolated(nodeLabel(compiled, nodeId) ?? nodeId);
  const outcome = (
    <Outcome
      result={result}
      compiled={compiled}
      simulation={simulation}
      onAnswer={onAnswer}
      name={name}
    />
  );
  return (
    <>
      {/* A question takes focus after an answer; any other outcome is announced. */}
      {result.outcome === "needs_input" ? outcome : <div role="status">{outcome}</div>}
      {/* A graph refused before its run starts has no path and no estimate. */}
      {result.entries > 0 && <Details result={result} compiled={compiled} name={name} />}
    </>
  );
}

type NameOf = (nodeId: string) => string;

function Outcome({ result, compiled, simulation, onAnswer, name }: ResultProps & { name: NameOf }) {
  switch (result.outcome) {
    case "completed":
      return <p className="text-foreground">The run completes.</p>;
    case "failed":
      return <p className="text-foreground">The run fails.</p>;
    case "cancelled":
      return <p className="text-foreground">The run is cancelled.</p>;
    case "paused": {
      const cause = result.view.causes[0] ?? null;
      const copy = pauseCopy(cause?.reason ?? null, cause, compiled);
      const first = copy.label === null ? "The run pauses." : `The run pauses: ${copy.label}.`;
      return <Lines first={first} rest={copy.body === UNKNOWN_PAUSE_TEXT ? [] : [copy.body]} />;
    }
    case "needs_input":
      return result.needs_input ? (
        <Question
          question={result.needs_input}
          simulation={simulation}
          onAnswer={onAnswer}
          name={name}
        />
      ) : null;
    case "rejected":
      return result.rejection ? <Refusal rejection={result.rejection} name={name} /> : null;
    case "stalled":
      return (
        <Lines
          first="No step can advance."
          rest={
            result.stall_code
              ? [`The engine refused an input Simulate made: ${result.stall_code}.`]
              : []
          }
        />
      );
    case "step_limit":
      return (
        <p className="text-foreground">{STOPPED_BY_TEXT[result.stopped_by ?? "transitions"]}</p>
      );
    case "unsupported":
      return (
        <p className="text-foreground">
          {result.unsupported_effect
            ? `The simulation stopped: Simulate cannot model the ${isolated(result.unsupported_effect)} action yet.`
            : "The simulation stopped: Simulate cannot model one of the run's actions yet."}
        </p>
      );
    default: {
      const unhandled: never = result.outcome;
      return unhandled;
    }
  }
}

function Question({
  question,
  simulation,
  onAnswer,
  name,
}: {
  question: SimNeedsInput;
  simulation: Simulation;
  onAnswer: (value: string) => void;
  name: NameOf;
}) {
  const labelId = useId();
  // An answer chosen while a request runs, or for an older text, would not be this question's.
  const disabled = simulation.isPending || simulation.stale;
  return (
    <div
      role="group"
      aria-labelledby={labelId}
      tabIndex={-1}
      data-question
      className="flex flex-wrap items-center gap-2 outline-none"
    >
      <p id={labelId} className="text-foreground">
        {`Choose a result for ${name(question.node_id)}:`}
      </p>
      {question.allowed_values.map((value) => (
        <Button
          key={value}
          variant="outline"
          size="sm"
          componentId="coral.simulate.answer"
          disabled={disabled}
          onClick={() => onAnswer(value)}
        >
          {question.kind === "done_when" ? (CHECK_RESULT_TEXT[value] ?? value) : value}
        </Button>
      ))}
    </div>
  );
}

/** A refused value, with what the node takes as text; Undo and Reset are the way on. */
function Refusal({ rejection, name }: { rejection: SimRejection; name: NameOf }) {
  const allowed = rejection.allowed_values;
  return (
    <Lines
      first={`${name(rejection.node_id)} cannot take ${isolated(rejection.value)}.`}
      rest={[
        allowed.length > 0
          ? `Allowed values: ${allowed.map(isolated).join(", ")}.`
          : "It takes no value here.",
      ]}
    />
  );
}

/** A step's result in words: its label, or whether its checks passed. */
function resultText(result: string): string {
  if (result === "evidence_missing") return "checks fail";
  return result.replace(/_/g, " ");
}

function Details({
  result,
  compiled,
  name,
}: {
  result: SimResult;
  compiled: CompiledGraph;
  name: NameOf;
}) {
  const loopName = (backArrowId: string) => {
    const arrow = compiled.arrows.find((candidate) => candidate.id === backArrowId);
    return arrow ? `${name(arrow.source)} → ${name(arrow.target)}` : isolated(backArrowId);
  };
  const { sessions } = result;
  const unused = result.outcome === "needs_input" ? [] : result.unconsumed;
  return (
    <div className="flex flex-col gap-2">
      {result.steps.length > 0 && (
        <TitledList
          title="Path"
          ordered
          items={result.steps.map((step) => `${name(step.node_id)}: ${resultText(step.result)}`)}
        />
      )}
      {result.loops.length > 0 && (
        <TitledList
          title="Loops"
          items={result.loops.map(
            (loop) =>
              `${loopName(loop.back_arrow_id)}: ${passText({ index: loop.passes, limit: loop.limit })}` +
              (loop.limit_hit ? ", limit reached" : ""),
          )}
        />
      )}
      <p className="text-foreground">
        {`Gates reached: ${result.gates_reached.length > 0 ? result.gates_reached.map(name).join(", ") : "none"}`}
      </p>
      <p className="text-foreground">{`Step activations: ${result.step_activations}`}</p>
      <Lines
        first={`Estimated sessions: ${sessions.total}`}
        rest={[
          `${sessions.steps} for steps, ${sessions.orchestrator} for an orchestrator and ` +
            `${sessions.anchor} for the run's anchor session. This is an estimate.`,
        ]}
      />
      {unused.length > 0 && (
        <TitledList
          title="Unused answers"
          items={unused.map(
            (input) => `${name(input.node_id)}: ${input.values.map(isolated).join(", ")}`,
          )}
        />
      )}
    </div>
  );
}

function TitledList({
  title,
  items,
  ordered = false,
}: {
  title: string;
  items: readonly string[];
  ordered?: boolean;
}) {
  const titleId = useId();
  const children: ReactNode = items.map((item, index) => (
    // Items repeat (a loop's passes), so their place is their identity.
    // oxlint-disable-next-line react/no-array-index-key
    <li key={index} className="text-foreground">
      {item}
    </li>
  ));
  const listClass = `flex flex-col gap-0.5 pl-5 ${ordered ? "list-decimal" : "list-disc"}`;
  return (
    <div className="flex flex-col gap-1">
      <h3 id={titleId} className="font-medium text-muted-foreground text-xs">
        {title}
      </h3>
      {ordered ? (
        <ol aria-labelledby={titleId} className={listClass}>
          {children}
        </ol>
      ) : (
        <ul aria-labelledby={titleId} className={listClass}>
          {children}
        </ul>
      )}
    </div>
  );
}

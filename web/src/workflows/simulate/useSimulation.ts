import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WorkflowsApiError, simulateWorkflow } from "../api/client";
import type {
  CompiledGraph,
  InvalidResult,
  SimResult,
  SimulatedResult,
} from "../api/generated/coralApi";
import { MAX_RETRY_AFTER_MS } from "../api/runsApi";
import { runOverlay, type NodeOverlay } from "../canvas/runOverlay";
import { scriptFromAnswers, type SimulationAnswer } from "./simulationScript";

// The editor's dry run: it posts the YAML and the answers so far on open and after each
// answer, undo, reset or re-run, never on typing; a newer request aborts the older one. An
// answer is taken only for the question on screen, with nothing in flight and the YAML unchanged.

/** Times a busy server's refusal is retried before the panel says so. */
export const BUSY_RETRIES = 3;
/** The shortest wait before posting to a busy server again, whatever Retry-After says. */
const MIN_BUSY_WAIT_MS = 1000;

export type SimulateResponse = SimulatedResult | InvalidResult;

export interface Simulation {
  /** The last response. */
  response: SimulateResponse | null;
  /** Its simulation, when the workflow loaded and was simulated. */
  simulation: SimResult | null;
  /** The graph the server compiled for it, when the workflow loaded. */
  compiled: CompiledGraph | null;
  /** The simulated run over `compiled`. */
  overlay: ReadonlyMap<string, NodeOverlay> | null;
  answers: readonly SimulationAnswer[];
  /** The YAML differs from the one the last request or the last response was for. */
  stale: boolean;
  isPending: boolean;
  /** "Simulate again" would post something new: no request for this YAML is in flight. */
  canRerun: boolean;
  /** Waiting out a busy server before posting the same request again. */
  busy: boolean;
  error: Error | null;
  answer: (value: string) => void;
  undo: () => void;
  reset: () => void;
  /** Post the same answers with the current YAML. */
  rerun: () => void;
}

interface State {
  answers: readonly SimulationAnswer[];
  postedYaml: string | null;
  response: SimulateResponse | null;
  /** The YAML the last response was for; kept after a post of new YAML drops that response. */
  responseYaml: string | null;
  isPending: boolean;
  busy: boolean;
  error: Error | null;
}

interface InFlight {
  controller: AbortController;
  /** Set while waiting out a busy server. */
  timer: ReturnType<typeof setTimeout> | null;
}

const IDLE: State = {
  answers: [],
  postedYaml: null,
  response: null,
  responseYaml: null,
  isPending: false,
  busy: false,
  error: null,
};

/** The server's own "busy" refusal; another 503, from a proxy say, is a failure. */
export const isServerBusy = (error: unknown): error is WorkflowsApiError =>
  error instanceof WorkflowsApiError && error.status === 503 && error.code === "server_busy";

const busyWaitMs = (error: WorkflowsApiError): number =>
  Math.min(Math.max(error.retryAfterMs ?? 0, MIN_BUSY_WAIT_MS), MAX_RETRY_AFTER_MS);

export function useSimulation(yaml: string, enabled: boolean): Simulation {
  const [state, setState] = useState<State>(IDLE);
  // Callbacks read the state from here, so one made before the last render cannot act on
  // an older question.
  const stateRef = useRef<State>(IDLE);
  const inFlight = useRef<InFlight | null>(null);
  const yamlRef = useRef(yaml);

  const commit = useCallback((update: (previous: State) => State) => {
    stateRef.current = update(stateRef.current);
    setState(stateRef.current);
  }, []);

  const cancel = useCallback(() => {
    const current = inFlight.current;
    if (current === null) return;
    current.controller.abort();
    if (current.timer !== null) clearTimeout(current.timer);
    inFlight.current = null;
  }, []);

  const post = useCallback(
    (answers: readonly SimulationAnswer[], postedYaml: string) => {
      cancel();
      const script = scriptFromAnswers(answers);
      const send = (retries: number) => {
        const current: InFlight = { controller: new AbortController(), timer: null };
        inFlight.current = current;
        simulateWorkflow(postedYaml, script, current.controller.signal).then(
          (response) => {
            if (inFlight.current !== current) return;
            inFlight.current = null;
            commit((previous) => ({
              ...previous,
              response,
              responseYaml: postedYaml,
              isPending: false,
              busy: false,
            }));
          },
          (error: unknown) => {
            if (inFlight.current !== current) return;
            if (isServerBusy(error) && retries < BUSY_RETRIES) {
              current.timer = setTimeout(() => send(retries + 1), busyWaitMs(error));
              commit((previous) => ({ ...previous, busy: true }));
              return;
            }
            inFlight.current = null;
            commit((previous) => ({
              ...previous,
              response: null,
              responseYaml: null,
              isPending: false,
              busy: false,
              error: error instanceof Error ? error : new Error(String(error)),
            }));
          },
        );
      };
      // A response for other YAML must not show as this request's while it runs.
      commit((previous) => ({
        ...previous,
        answers,
        postedYaml,
        response: previous.responseYaml === postedYaml ? previous.response : null,
        isPending: true,
        busy: false,
        error: null,
      }));
      send(0);
    },
    [cancel, commit],
  );

  useEffect(() => {
    yamlRef.current = yaml;
  }, [yaml]);

  useEffect(() => {
    if (!enabled) return undefined;
    post([], yamlRef.current);
    return () => {
      cancel();
      commit(() => IDLE);
    };
  }, [enabled, post, cancel, commit]);

  const { response } = state;
  const simulation = response?.valid ? response.simulation : null;
  const compiled = response?.valid ? response.compiled : null;
  const overlay = useMemo(
    () => (compiled && simulation ? runOverlay(compiled, simulation.view) : null),
    [compiled, simulation],
  );
  const stale =
    (state.postedYaml !== null && state.postedYaml !== yaml) ||
    (state.responseYaml !== null && state.responseYaml !== yaml);

  // Each action is refused while a request is in flight, and all but reset and re-run while
  // the YAML differs from what the answers were chosen for.
  const current = (): State | null => {
    const latest = stateRef.current;
    return inFlight.current === null && latest.postedYaml === yaml ? latest : null;
  };
  const answer = (value: string) => {
    const latest = current();
    const question = latest?.response?.valid ? latest.response.simulation?.needs_input : null;
    if (!latest || !question) return;
    post([...latest.answers, { nodeId: question.node_id, kind: question.kind, value }], yaml);
  };
  const undo = () => {
    const latest = current();
    if (latest && latest.answers.length > 0) post(latest.answers.slice(0, -1), yaml);
  };
  const reset = () => {
    if (inFlight.current === null && stateRef.current.answers.length > 0) post([], yaml);
  };
  const rerun = () => {
    // A second click on the same request would only abort it and post it again.
    if (inFlight.current !== null && stateRef.current.postedYaml === yaml) return;
    post(stateRef.current.answers, yaml);
  };

  return {
    response,
    simulation,
    compiled,
    overlay,
    answers: state.answers,
    stale,
    isPending: state.isPending,
    canRerun: !(state.isPending && state.postedYaml === yaml),
    busy: state.busy,
    error: state.error,
    answer,
    undo,
    reset,
    rerun,
  };
}

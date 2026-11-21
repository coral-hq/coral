import { authenticatedFetch } from "@/lib/identity";
import { isRetryableRequestError } from "@/lib/queryRetry";
import { ApiError, apiErrorFromResponse } from "@/lib/sessionsApi";
import { isRecord } from "@/lib/toolValue";
import type { CoralOperations, RunDetail } from "./generated/coralApi";

// The runs API client (`/v1/coral/runs`). A refusal in Coral's envelope is thrown as a
// `CoralRequestError` with its status, code, message, `Retry-After` and details; any other
// failure as an `ApiError`. Paths and bodies are typed from the generated operations, so a
// renamed route fails the type check.

/** A lifecycle action, as a run's `allowed_actions` names it. */
export type RunAction = RunDetail["allowed_actions"][number];

/** A run's status, as every run route names it. */
export type RunStatus = RunDetail["status"];

/** The runs list's filters: no statuses means every status. */
export interface RunFilters {
  statuses: readonly RunStatus[];
  workflowId: string | null;
}

type Operation<Name extends keyof CoralOperations> = CoralOperations[Name];
type RunActionOperation = Operation<`coral_${RunAction}_run`>;
type ListRunsQuery = Operation<"coral_list_runs">["query"];

const RUNS_PATH = "/v1/coral/runs" satisfies Operation<"coral_list_runs">["path"];
const RUN_PATH = "/v1/coral/runs/{run_id}" satisfies Operation<"coral_get_run">["path"];
const GRAPH_PATH =
  "/v1/coral/runs/{run_id}/graph" satisfies Operation<"coral_get_run_graph">["path"];
const OUTCOME_PATH =
  "/v1/coral/runs/{run_id}/outcome" satisfies Operation<"coral_get_run_outcome">["path"];
const STREAM_PATH =
  "/v1/coral/runs/{run_id}/stream" satisfies Operation<"coral_stream_run">["path"];
const ANSWER_PATH =
  "/v1/coral/runs/{run_id}/gates/{node_id}:answer" satisfies Operation<"coral_answer_gate">["path"];
const POST: Operation<"coral_start_run">["method"] &
  Operation<"coral_answer_gate">["method"] &
  RunActionOperation["method"] = "POST";
// Resume sends no cap, so every action posts the empty object.
const NO_ARGUMENTS: RunActionOperation["body"] = {};
/** The longest a client waits on a refusal's `Retry-After`, whatever it asks for. */
export const MAX_RETRY_AFTER_MS = 60_000;
/** Runs read per page of the runs list. */
export const RUNS_PAGE_SIZE: NonNullable<ListRunsQuery["limit"]> = 25;
// Dot segments would be resolved away by URL parsing, leaving the run's path.
const NOT_PATH_IDS: ReadonlySet<string> = new Set(["", ".", ".."]);

/** A refusal in Coral's envelope, with its machine-readable `details` (`details.reason`). */
export class CoralRequestError extends ApiError {
  readonly details: Readonly<Record<string, unknown>> | null;

  constructor(
    message: string,
    status: number,
    code: string | null,
    details: Readonly<Record<string, unknown>> | null,
    retryAfterMs: number | null = null,
  ) {
    super(message, status, code, retryAfterMs);
    this.name = "CoralRequestError";
    this.details = details;
  }
}

/** The `details` of Coral's envelope (which always sends the key), else `undefined`. */
function coralDetails(body: unknown): Record<string, unknown> | null | undefined {
  if (!isRecord(body) || !isRecord(body.error)) return undefined;
  const { code, message, details } = body.error;
  if (typeof code !== "string" || typeof message !== "string" || !("details" in body.error)) {
    return undefined;
  }
  if (details === null || isRecord(details)) return details;
  return undefined;
}

/** The error for a failed response: a `CoralRequestError` only for Coral's own envelope. */
export async function coralError(response: Response): Promise<ApiError> {
  const error = await apiErrorFromResponse(response.clone());
  let details: Record<string, unknown> | null | undefined;
  try {
    details = coralDetails(await response.json());
  } catch {
    // Not JSON: the plain error already holds the status line.
    return error;
  }
  if (details === undefined) return error;
  return new CoralRequestError(
    error.message,
    error.status,
    error.code,
    details,
    error.retryAfterMs,
  );
}

/** Whether `error` is a runs route's 404: the run is gone, or not the caller's. */
export const isRunNotFound = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 404;

/** A run read's retry rule: once for a failure a retry can fix; a 404 or another refusal is final. */
export const retryRunRead = (failureCount: number, error: unknown): boolean =>
  failureCount < 1 && isRetryableRequestError(error);

/** The key of a run's detail in the viewer's `scope`. */
export const runQueryKey = (scope: string, runId: string) => ["coral-run", scope, runId] as const;

/** The key of a run's streamed view; only the stream controller writes it. */
export const runViewQueryKey = (scope: string, runId: string) =>
  ["coral-run-view", scope, runId] as const;

/** The key of a run's pinned graph, which never changes. */
export const runGraphQueryKey = (scope: string, runId: string) =>
  ["coral-run-graph", scope, runId] as const;

/** The key of a finished run's outcome. */
export const runOutcomeQueryKey = (scope: string, runId: string) =>
  ["coral-run-outcome", scope, runId] as const;

/** The prefix of every runs list key in `scope`, which a start or a run action makes stale. */
export const runsListPrefixKey = (scope: string) => ["coral-runs", scope] as const;

/** The key of the runs list under `filters`; the same status set in any order is one key. */
export const runsListQueryKey = (scope: string, filters: RunFilters) => {
  const statuses: readonly RunStatus[] = [...new Set(filters.statuses)].sort();
  const normalized: RunFilters = { statuses, workflowId: filters.workflowId };
  return [...runsListPrefixKey(scope), normalized] as const;
};

/** The key of a run's pause, resume and cancel requests, so every view of the run sees one in flight. */
export const runActionKey = (scope: string, runId: string) =>
  ["coral-run-action", scope, runId] as const;

const actionPath = (action: RunAction): RunActionOperation["path"] => `${RUN_PATH}:${action}`;

/** One path segment for `id`; an id that cannot name one is the run 404 without a request. */
function segment(id: string): string {
  if (NOT_PATH_IDS.has(id)) {
    throw new CoralRequestError("Run not found.", 404, "not_found", null);
  }
  return encodeURIComponent(id);
}

/** `path` for one run. */
function runUrl(path: string, runId: string): string {
  const runSegment = segment(runId);
  return path.replace("{run_id}", () => runSegment);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await coralError(response);
  return (await response.json()) as T;
}

function postJson(url: string, body: unknown): Promise<Response> {
  return authenticatedFetch(url, {
    method: POST,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** One of the caller's runs in full; any run they cannot see is a 404. */
export async function getRun(
  runId: string,
  signal?: AbortSignal,
): Promise<Operation<"coral_get_run">["response"]> {
  return readJson(await authenticatedFetch(runUrl(RUN_PATH, runId), { signal }));
}

/** One page of the caller's runs, newest first; `after` is the last page's `next_cursor`. */
export async function listRuns(
  filters: RunFilters,
  after?: string,
  signal?: AbortSignal,
): Promise<Operation<"coral_list_runs">["response"]> {
  const params = new URLSearchParams();
  const add = (name: keyof ListRunsQuery, value: string) => params.append(name, value);
  add("limit", String(RUNS_PAGE_SIZE));
  for (const status of filters.statuses) add("status", status);
  if (filters.workflowId !== null) add("workflow_id", filters.workflowId);
  if (after !== undefined) add("after", after);
  return readJson(await authenticatedFetch(`${RUNS_PATH}?${params.toString()}`, { signal }));
}

/** The workflow graph a run is pinned to. */
export async function getRunGraph(
  runId: string,
  signal?: AbortSignal,
): Promise<Operation<"coral_get_run_graph">["response"]> {
  return readJson(await authenticatedFetch(runUrl(GRAPH_PATH, runId), { signal }));
}

/** What a run produced: its branch, checkout commands and, once finished, its diff. */
export async function getRunOutcome(
  runId: string,
  signal?: AbortSignal,
): Promise<Operation<"coral_get_run_outcome">["response"]> {
  return readJson(await authenticatedFetch(runUrl(OUTCOME_PATH, runId), { signal }));
}

/** The path of a run's event stream, which the stream client opens itself. */
export function runStreamUrl(runId: string): string {
  return runUrl(STREAM_PATH, runId);
}

/** Pause, resume (without a cap) or cancel a run; an action already in effect is a no-op. */
export async function postRunAction(
  runId: string,
  action: RunAction,
): Promise<RunActionOperation["response"]> {
  return readJson(await postJson(runUrl(actionPath(action), runId), NO_ARGUMENTS));
}

/** Answer a visit of a run's gate; a refusal keeps its reason in `details.reason`. */
export async function answerGate(
  runId: string,
  nodeId: string,
  body: Operation<"coral_answer_gate">["body"],
): Promise<Operation<"coral_answer_gate">["response"]> {
  const nodeSegment = segment(nodeId);
  const url = runUrl(ANSWER_PATH, runId).replace("{node_id}", () => nodeSegment);
  return readJson(await postJson(url, body));
}

/** Start a workflow: 201 with the new run, or 200 with the run the same start key began. */
export async function startRun(
  body: Operation<"coral_start_run">["body"],
): Promise<Operation<"coral_start_run">["response"]> {
  return readJson(await postJson(RUNS_PATH, body));
}

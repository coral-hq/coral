import { authenticatedFetch } from "@/lib/identity";
import { ApiError, apiErrorFromResponse } from "@/lib/sessionsApi";
import type { CoralOperations, RunDetail } from "./generated/coralApi";

// The runs API client (`/v1/coral/runs`). A refusal's Coral envelope is thrown as an
// `ApiError` with its status, code, message and `Retry-After`. Paths and bodies are typed
// from the generated operations, so a renamed route fails the type check.

/** A lifecycle action, as a run's `allowed_actions` names it. */
export type RunAction = RunDetail["allowed_actions"][number];

type RunActionOperation = CoralOperations[`coral_${RunAction}_run`];

const RUN_PATH = "/v1/coral/runs/{run_id}" satisfies CoralOperations["coral_get_run"]["path"];
const ACTION_METHOD: RunActionOperation["method"] = "POST";
// Resume sends no cap, so every action posts the empty object.
const NO_ARGUMENTS: RunActionOperation["body"] = {};
// Dot segments would be resolved away by URL parsing, leaving the run's path.
const NOT_RUN_IDS: ReadonlySet<string> = new Set(["", ".", ".."]);

export const runQueryKey = (runId: string) => ["coral-run", runId] as const;

/** The key of a run's pause, resume and cancel requests, so every view of the run sees one in flight. */
export const runActionKey = (runId: string) => ["coral-run-action", runId] as const;

const actionPath = (action: RunAction): RunActionOperation["path"] => `${RUN_PATH}:${action}`;

/** `path` for one run; an id that cannot name a run is a 404 without a request. */
function runUrl(path: string, runId: string): string {
  if (NOT_RUN_IDS.has(runId)) throw new ApiError("Run not found.", 404, "not_found");
  const segment = encodeURIComponent(runId);
  return path.replace("{run_id}", () => segment);
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await apiErrorFromResponse(response);
  return (await response.json()) as T;
}

/** One of the caller's runs in full; any run they cannot see is a 404. */
export async function getRun(
  runId: string,
  signal?: AbortSignal,
): Promise<CoralOperations["coral_get_run"]["response"]> {
  return readJson(await authenticatedFetch(runUrl(RUN_PATH, runId), { signal }));
}

/** Pause, resume (without a cap) or cancel a run; an action already in effect is a no-op. */
export async function postRunAction(
  runId: string,
  action: RunAction,
): Promise<RunActionOperation["response"]> {
  const response = await authenticatedFetch(runUrl(actionPath(action), runId), {
    method: ACTION_METHOD,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(NO_ARGUMENTS),
  });
  return readJson(response);
}

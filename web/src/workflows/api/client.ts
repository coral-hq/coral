import { authenticatedFetch } from "@/lib/identity";
import type {
  PreflightResult,
  StartRunRequest,
  StartRunResult,
  ValidateResponse,
  WorkflowDetail,
  WorkflowSummary,
  WorkflowTemplate,
} from "./workflowTypes";
import { stubPreflight, stubStartRun, stubTemplates } from "./msw/handlers";

const BASE = "/v1/coral";

export const WORKFLOWS_QUERY_KEY = ["coral-workflows"] as const;
export const workflowQueryKey = (workflowKey: string) => ["coral-workflow", workflowKey] as const;

export class WorkflowsApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "WorkflowsApiError";
    this.status = status;
  }
}

/** No retry on 4xx; one retry on 5xx or network errors. */
export function shouldRetryWorkflows(failureCount: number, error: unknown): boolean {
  if (error instanceof WorkflowsApiError && error.status < 500) return false;
  return failureCount < 1;
}

async function readJson<T>(response: Response, what: string): Promise<T> {
  if (!response.ok) {
    throw new WorkflowsApiError(`Failed to ${what} (${response.status})`, response.status);
  }
  return (await response.json()) as T;
}

function postYaml(path: string, yaml: string, signal?: AbortSignal): Promise<Response> {
  return authenticatedFetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml }),
    signal,
  });
}

/** Server validation; load errors are a 200 with `load_error`, not an exception. */
export async function validateWorkflow(
  yaml: string,
  signal?: AbortSignal,
): Promise<ValidateResponse> {
  return readJson(await postYaml("/workflows:validate", yaml, signal), "validate workflow");
}

export async function listWorkflows(signal?: AbortSignal): Promise<WorkflowSummary[]> {
  const payload = await readJson<unknown>(
    await authenticatedFetch(`${BASE}/workflows`, { signal }),
    "list workflows",
  );
  if (!Array.isArray(payload)) throw new WorkflowsApiError("Invalid workflow list response", 502);
  return payload as WorkflowSummary[];
}

/** `workflowId` is the stored definition id, not the workflow key. */
export async function getWorkflow(
  workflowId: string,
  signal?: AbortSignal,
): Promise<WorkflowDetail> {
  return readJson(
    await authenticatedFetch(`${BASE}/workflows/${encodeURIComponent(workflowId)}`, { signal }),
    "load workflow",
  );
}

/** The editor route carries the workflow key; resolve it to the stored definition. */
export async function getWorkflowByKey(
  workflowKey: string,
  signal?: AbortSignal,
): Promise<WorkflowDetail> {
  const match = (await listWorkflows(signal)).find((item) => item.workflow_key === workflowKey);
  if (!match) throw new WorkflowsApiError(`Workflow ${workflowKey} not found`, 404);
  return getWorkflow(match.id, signal);
}

export async function saveWorkflow(yaml: string): Promise<WorkflowSummary & ValidateResponse> {
  return readJson(await postYaml("/workflows", yaml), "save workflow");
}

// Templates, preflight and runs have no backend yet; these resolve locally so the
// UI shape is final and only these three bodies change when the APIs land.

export function listTemplates(): Promise<WorkflowTemplate[]> {
  return stubTemplates();
}

export function runPreflight(request: StartRunRequest): Promise<PreflightResult> {
  return stubPreflight(request);
}

export function startRun(request: StartRunRequest): Promise<StartRunResult> {
  return stubStartRun(request);
}

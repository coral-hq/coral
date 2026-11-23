import { authenticatedFetch } from "@/lib/identity";
import { apiErrorFromResponse } from "@/lib/sessionsApi";
import type {
  CoralOperations,
  InvalidResult,
  SavedWorkflowOut,
  SimScript,
  SimulatedResult,
  TemplateOut,
} from "./generated/coralApi";
import type { ValidateResponse, WorkflowDetail, WorkflowSummary } from "./workflowTypes";

const BASE = "/v1/coral";

type Operation<Name extends keyof CoralOperations> = CoralOperations[Name];

const TEMPLATES_PATH = "/v1/coral/templates" satisfies Operation<"coral_list_templates">["path"];
const USE_TEMPLATE_PATH =
  "/v1/coral/templates/{template_id}:use" satisfies Operation<"coral_use_template">["path"];
const SIMULATE_PATH =
  "/v1/coral/workflows:simulate" satisfies Operation<"coral_simulate_workflow">["path"];
const NO_ARGUMENTS: Operation<"coral_use_template">["body"] = {};

export const WORKFLOWS_QUERY_KEY = ["coral-workflows"] as const;
export const TEMPLATES_QUERY_KEY = ["coral-templates"] as const;
export const workflowQueryKey = (workflowKey: string) => ["coral-workflow", workflowKey] as const;

export class WorkflowsApiError extends Error {
  readonly status: number;
  /** The response's `Retry-After`, in milliseconds, when it sent one. */
  readonly retryAfterMs: number | null;
  /** The refusal's `error.code` in Coral's envelope, such as `server_busy`. */
  readonly code: string | null;

  constructor(
    message: string,
    status: number,
    retryAfterMs: number | null = null,
    code: string | null = null,
  ) {
    super(message);
    this.name = "WorkflowsApiError";
    this.status = status;
    this.retryAfterMs = retryAfterMs;
    this.code = code;
  }
}

/** No retry on 4xx; one retry on 5xx or network errors. */
export function shouldRetryWorkflows(failureCount: number, error: unknown): boolean {
  if (error instanceof WorkflowsApiError && error.status < 500) return false;
  return failureCount < 1;
}

async function readJson<T>(response: Response, what: string): Promise<T> {
  if (!response.ok) {
    const { retryAfterMs, code } = await apiErrorFromResponse(response);
    throw new WorkflowsApiError(
      `Failed to ${what} (${response.status})`,
      response.status,
      retryAfterMs,
      code,
    );
  }
  return (await response.json()) as T;
}

function postJson(url: string, body: unknown, signal?: AbortSignal): Promise<Response> {
  return authenticatedFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

function postYaml(path: string, yaml: string, signal?: AbortSignal): Promise<Response> {
  return postJson(`${BASE}${path}`, { yaml }, signal);
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

/** The built-in templates, in gallery order. */
export async function listTemplates(signal?: AbortSignal): Promise<TemplateOut[]> {
  const payload = await readJson<unknown>(
    await authenticatedFetch(TEMPLATES_PATH, { signal }),
    "list templates",
  );
  if (!Array.isArray(payload)) throw new WorkflowsApiError("Invalid template list response", 502);
  return payload as TemplateOut[];
}

/** A new workflow of the caller's made from a template; an existing one is never replaced. */
export async function createFromTemplate(templateId: string): Promise<SavedWorkflowOut> {
  const url = USE_TEMPLATE_PATH.replace("{template_id}", () => encodeURIComponent(templateId));
  return readJson(await postJson(url, NO_ARGUMENTS), "use template");
}

/** A dry run of `yaml` answered from `script`; load errors are a 200, as validation's are. */
export async function simulateWorkflow(
  yaml: string,
  script: SimScript,
  signal?: AbortSignal,
): Promise<SimulatedResult | InvalidResult> {
  const body: Operation<"coral_simulate_workflow">["body"] = { yaml, script };
  return readJson(await postJson(SIMULATE_PATH, body, signal), "simulate workflow");
}

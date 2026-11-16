// Local stand-ins for endpoints that do not exist yet (templates, preflight, runs).
// Named for the planned MSW layer; plain async functions keep the client mockable
// without a service worker.

import { PR_REVIEW_YAML } from "../../fixtures";
import type {
  PreflightResult,
  StartRunRequest,
  StartRunResult,
  WorkflowTemplate,
} from "../workflowTypes";

export const PR_REVIEW_TEMPLATE: WorkflowTemplate = {
  id: "pr-review",
  name: "PR review",
  description: "Find open PRs, review them, fix findings (up to 3 rounds), then approve and merge.",
  yaml: PR_REVIEW_YAML,
};

export async function stubTemplates(): Promise<WorkflowTemplate[]> {
  return [PR_REVIEW_TEMPLATE];
}

export async function stubPreflight(request: StartRunRequest): Promise<PreflightResult> {
  const items = [
    { id: "workspace", label: "Workspace is reachable", ok: request.workspace_path.length > 0 },
    { id: "host", label: "Host is online", ok: request.host_id.length > 0 },
  ];
  return { ok: items.every((item) => item.ok), items };
}

let stubRunCounter = 0;

export async function stubStartRun(_request: StartRunRequest): Promise<StartRunResult> {
  stubRunCounter += 1;
  return { run_id: `stub-run-${stubRunCounter}` };
}

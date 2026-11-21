// Local stand-ins for endpoints that do not exist yet (templates). Named for the planned
// MSW layer; plain async functions keep the client mockable without a service worker.

import { PR_REVIEW_YAML } from "../../fixtures";
import type { WorkflowTemplate } from "../workflowTypes";

export const PR_REVIEW_TEMPLATE: WorkflowTemplate = {
  id: "pr-review",
  name: "PR review",
  description: "Find open PRs, review them, fix findings (up to 3 rounds), then approve and merge.",
  yaml: PR_REVIEW_YAML,
};

export async function stubTemplates(): Promise<WorkflowTemplate[]> {
  return [PR_REVIEW_TEMPLATE];
}

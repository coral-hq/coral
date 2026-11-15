const WORKFLOWS_PATH = "/workflows";
const PROFILES_PATH = "/profiles";

type Rebase = (path: string) => string;
const identity: Rebase = (path) => path;

export interface RunPathFocus {
  agent?: string;
  node?: string;
  scope?: string;
  panel?: string;
}

export function workflowsPath(): string {
  return WORKFLOWS_PATH;
}

export function profilesPath(): string {
  return PROFILES_PATH;
}

export function workflowPath(workflowKey: string): string {
  return `${WORKFLOWS_PATH}/${encodeURIComponent(workflowKey)}`;
}

/** Run view URL; focus rides the query string (`?agent=&node=&scope=&panel=`). */
export function runPath(runId: string, focus: RunPathFocus = {}): string {
  const params = new URLSearchParams();
  for (const key of ["agent", "node", "scope", "panel"] as const) {
    const value = focus[key];
    if (value) params.set(key, value);
  }
  const search = params.toString();
  return `${WORKFLOWS_PATH}/runs/${encodeURIComponent(runId)}${search ? `?${search}` : ""}`;
}

function isUnder(pathname: string, root: string): boolean {
  if (!pathname.startsWith(root)) return false;
  const boundary = pathname[root.length];
  return boundary === undefined || boundary === "/";
}

/** `/workflows` and everything below it, under the current mount path. */
export function isWorkflowsPathname(pathname: string, rebase: Rebase = identity): boolean {
  return isUnder(pathname, rebase(WORKFLOWS_PATH));
}

export function isProfilesPathname(pathname: string, rebase: Rebase = identity): boolean {
  return isUnder(pathname, rebase(PROFILES_PATH));
}

/** Any Coral desk route; these never light "New session". */
export function isCoralDeskPath(pathname: string, rebase: Rebase = identity): boolean {
  return isWorkflowsPathname(pathname, rebase) || isProfilesPathname(pathname, rebase);
}

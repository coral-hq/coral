import type { RunFilters, RunStatus } from "../../api/runsApi";

// The runs history's filters as the desk's URL carries them: one status chip in `?status=`
// and one workflow id in `?workflow=`. A value the server would refuse reads as no filter,
// so a hand-edited link still lists runs.

export type RunStatusChip = "all" | "running" | "paused" | "completed" | "failed" | "cancelled";

export interface RunStatusChipOption {
  id: RunStatusChip;
  label: string;
  /** The statuses the list asks for; none means every status. */
  statuses: readonly RunStatus[];
}

/** The status chips in order, All first; Running covers runs still setting up. */
export const RUN_STATUS_CHIPS: readonly RunStatusChipOption[] = [
  { id: "all", label: "All", statuses: [] },
  { id: "running", label: "Running", statuses: ["starting", "running"] },
  { id: "paused", label: "Paused", statuses: ["paused"] },
  { id: "completed", label: "Completed", statuses: ["completed"] },
  { id: "failed", label: "Failed", statuses: ["failed"] },
  { id: "cancelled", label: "Cancelled", statuses: ["cancelled"] },
];

export interface RunListFilters {
  status: RunStatusChip;
  /** A stored workflow definition's id, or `null` for every workflow. */
  workflowId: string | null;
}

export const ALL_RUNS: RunListFilters = { status: "all", workflowId: null };

const STATUS_PARAM = "status";
const WORKFLOW_PARAM = "workflow";
// The runs route's `workflow_id` pattern.
const WORKFLOW_ID = /^[0-9a-f]{32}$/;

const CHIPS: ReadonlyMap<string, RunStatusChipOption> = new Map(
  RUN_STATUS_CHIPS.map((chip) => [chip.id, chip]),
);

/** The filters `search` names. */
export function runListFilters(search: URLSearchParams): RunListFilters {
  const status = CHIPS.get(search.get(STATUS_PARAM) ?? "")?.id ?? "all";
  const workflow = search.get(WORKFLOW_PARAM);
  return { status, workflowId: workflow !== null && WORKFLOW_ID.test(workflow) ? workflow : null };
}

/** What the runs list asks the server for under `filters`. */
export function runsQueryFilters(filters: RunListFilters): RunFilters {
  return {
    statuses: CHIPS.get(filters.status)?.statuses ?? [],
    workflowId: filters.workflowId,
  };
}

/** `search` with `filters` written in, leaving its other parameters; defaults are left out. */
export function searchWithRunFilters(
  search: URLSearchParams,
  filters: RunListFilters,
): URLSearchParams {
  const next = new URLSearchParams(search);
  if (filters.status === "all") next.delete(STATUS_PARAM);
  else next.set(STATUS_PARAM, filters.status);
  if (filters.workflowId === null) next.delete(WORKFLOW_PARAM);
  else next.set(WORKFLOW_PARAM, filters.workflowId);
  return next;
}

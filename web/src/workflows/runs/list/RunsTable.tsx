import {
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type InfiniteData,
} from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useNow } from "@/hooks/useNow";
import { Link, useSearchParams } from "@/lib/routing";
import { formatRunDuration, formatRunTimestamp } from "@/lib/scheduleText";
import { WORKFLOWS_QUERY_KEY, listWorkflows, shouldRetryWorkflows } from "../../api/client";
import type { RunPage, RunSummary } from "../../api/generated/coralApi";
import { listRuns, retryRunRead, runsListQueryKey } from "../../api/runsApi";
import { runPath } from "../../nav/coralPaths";
import { RunStatusPill } from "../../shared/RunStatusPill";
import { useCoralScope } from "../../shared/viewerScope";
import { spendText } from "../RunHeaderBar";
import {
  ALL_RUNS,
  RUN_STATUS_CHIPS,
  runListFilters,
  runsQueryFilters,
  searchWithRunFilters,
  type RunListFilters,
} from "./runFilters";

// The desk's runs history: the caller's runs, newest first, 25 a page, filtered by status
// and workflow from the URL. Spend is the server's cached figure, shown and never capped.
// A poll rereads every loaded page, so the list polls only while one page is loaded;
// with more, Refresh goes back to the first page.

/** A poll while a run on the page is starting or running. */
export const ACTIVE_POLL_MS = 10_000;
/** A poll while the page's only unsettled runs are paused. */
export const PAUSED_POLL_MS = 60_000;
/**
 * One more read after a first page that lacked a run's spend. The list serves cached spend
 * only and queues a refresh on a miss; the app never refetches on window focus, so without
 * this a settled page would keep "—" until a remount or a filter change.
 */
export const SPEND_FILL_MS = 5_000;

const UNKNOWN = "—";

type RunsData = InfiniteData<RunPage, string | null>;

/**
 * How long until the list reads its page again, or `false` for no poll.
 *
 * :param reads: How many times the list's data has been written, so the spend follow-up
 *     happens once.
 */
export function runsPollMs(data: RunsData | undefined, reads: number): number | false {
  if (data === undefined || data.pages.length !== 1) return false;
  const runs = data.pages[0]!.data;
  if (runs.some((run) => run.status === "starting" || run.status === "running")) {
    return ACTIVE_POLL_MS;
  }
  if (runs.some((run) => run.status === "paused")) return PAUSED_POLL_MS;
  if (reads === 1 && runs.some((run) => run.spend === null)) return SPEND_FILL_MS;
  return false;
}

export function RunsTable() {
  const { scope, ready } = useCoralScope();
  const queryClient = useQueryClient();
  const [search, setSearch] = useSearchParams();
  const filters = runListFilters(search);
  const queryFilters = runsQueryFilters(filters);
  const queryKey = runsListQueryKey(scope, queryFilters);
  const workflows = useQuery({
    queryKey: WORKFLOWS_QUERY_KEY,
    retry: shouldRetryWorkflows,
    queryFn: ({ signal }) => listWorkflows(signal),
  });
  const runs = useInfiniteQuery({
    queryKey,
    queryFn: ({ pageParam, signal }) => listRuns(queryFilters, pageParam ?? undefined, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    enabled: ready,
    retry: retryRunRead,
    refetchInterval: (query) => runsPollMs(query.state.data, query.state.dataUpdateCount),
  });

  const setFilters = (next: RunListFilters) => setSearch(searchWithRunFilters(search, next));
  // Keep only the first page, then reread it.
  const refresh = () => {
    queryClient.setQueryData<RunsData>(
      queryKey,
      (data) => data && { pages: data.pages.slice(0, 1), pageParams: data.pageParams.slice(0, 1) },
    );
    void queryClient.invalidateQueries({ queryKey, exact: true });
  };

  const pages = runs.data?.pages ?? [];
  const names = new Map((workflows.data ?? []).map((workflow) => [workflow.id, workflow.name]));
  const filtered = filters.status !== ALL_RUNS.status || filters.workflowId !== null;

  return (
    <div className="flex flex-col gap-3 py-3" data-testid="runs-table">
      <div className="flex flex-wrap items-center gap-2">
        <div role="group" aria-label="Status" className="flex flex-wrap gap-1">
          {RUN_STATUS_CHIPS.map((chip) => (
            <Button
              key={chip.id}
              size="sm"
              variant={chip.id === filters.status ? "secondary" : "ghost"}
              aria-pressed={chip.id === filters.status}
              componentId="coral.desk.runs_status"
              onClick={() => setFilters({ ...filters, status: chip.id })}
            >
              {chip.label}
            </Button>
          ))}
        </div>
        <select
          aria-label="Workflow"
          value={filters.workflowId ?? ""}
          onChange={(event) => setFilters({ ...filters, workflowId: event.target.value || null })}
          className="h-7 max-w-[16rem] rounded-md border border-border bg-background px-2 text-ui"
        >
          <option value="">All workflows</option>
          {(workflows.data ?? []).map((workflow) => (
            <option key={workflow.id} value={workflow.id}>
              {workflow.name}
            </option>
          ))}
          {filters.workflowId !== null && !names.has(filters.workflowId) && (
            <option value={filters.workflowId}>Unknown workflow</option>
          )}
        </select>
        {pages.length > 1 && (
          <Button
            variant="outline"
            size="sm"
            className="ml-auto"
            componentId="coral.desk.runs_refresh"
            onClick={refresh}
          >
            Refresh
          </Button>
        )}
      </div>

      {runs.data === undefined ? (
        runs.isError ? (
          <div className="flex flex-col items-center gap-3 py-16 text-center">
            <p role="alert" className="text-muted-foreground text-ui">
              Couldn't load runs.
            </p>
            <Button variant="outline" loading={runs.isFetching} onClick={() => void runs.refetch()}>
              Retry
            </Button>
          </div>
        ) : (
          <div
            role="status"
            className="flex items-center justify-center gap-2 py-16 text-muted-foreground text-ui"
          >
            <Spinner role="presentation" aria-hidden="true" className="size-4" />
            <span>Loading runs…</span>
          </div>
        )
      ) : pages.every((runPage) => runPage.data.length === 0) ? (
        <p className="py-16 text-center text-muted-foreground text-ui">
          {filtered ? "No runs match these filters." : "No runs yet. Start one from a workflow."}
        </p>
      ) : (
        <RunRows runs={pages.flatMap((runPage) => runPage.data)} names={names} />
      )}

      {runs.isFetchNextPageError && (
        <p role="alert" className="text-center text-destructive text-ui">
          Couldn't load more runs.
        </p>
      )}
      {runs.hasNextPage && (
        <Button
          variant="outline"
          size="sm"
          className="self-center"
          componentId="coral.desk.runs_load_more"
          loading={runs.isFetchingNextPage}
          onClick={() => void runs.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </div>
  );
}

const COLUMNS = ["Run", "Workflow", "Status", "Started", "Duration", "Spend (estimate)", "Branch"];

function RunRows({
  runs,
  names,
}: {
  runs: readonly RunSummary[];
  names: ReadonlyMap<string, string>;
}) {
  const now = useNow();
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table aria-label="Runs" className="w-full text-left text-ui">
        <thead>
          <tr className="border-border border-b bg-muted/50">
            {COLUMNS.map((column) => (
              <th key={column} scope="col" className="px-3 py-2 font-medium text-muted-foreground">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr
              key={run.run_id}
              data-testid="run-row"
              className="border-border border-b last:border-b-0 hover:bg-muted/30"
            >
              <td className="max-w-xs truncate px-3 py-2">
                <Link
                  to={runPath(run.run_id)}
                  componentId="coral.desk.open_run"
                  title={run.title}
                  className="text-foreground hover:underline"
                >
                  {run.title}
                </Link>
              </td>
              <td className="max-w-[12rem] truncate px-3 py-2 text-muted-foreground">
                {names.get(run.workflow_id) ?? UNKNOWN}
              </td>
              <td className="px-3 py-2">
                <RunStatusPill
                  status={run.status}
                  pauseReason={run.pause_reason}
                  openGates={null}
                />
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">
                <time dateTime={isoTime(run.created_at)}>
                  {formatRunTimestamp(run.created_at, now) ?? UNKNOWN}
                </time>
              </td>
              <td className="whitespace-nowrap px-3 py-2 text-muted-foreground tabular-nums">
                {durationText(run, now)}
              </td>
              <td className="whitespace-nowrap px-3 py-2 tabular-nums">{spendText(run.spend)}</td>
              <td className="whitespace-nowrap px-3 py-2">
                <code className="font-mono text-muted-foreground text-xs">{run.run_branch}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** An epoch-seconds instant as ISO text, or nothing for one no `Date` can hold. */
function isoTime(epochSeconds: number): string | undefined {
  const date = new Date(epochSeconds * 1000);
  return Number.isNaN(date.getTime()) ? undefined : date.toISOString();
}

/** A finished run's length, or how long an unfinished one has run so far. */
function durationText(run: RunSummary, now: Date): string {
  if (run.finished_at !== null)
    return formatRunDuration(run.created_at, run.finished_at) ?? UNKNOWN;
  const elapsed = formatRunDuration(run.created_at, Math.floor(now.getTime() / 1000));
  return elapsed === null ? UNKNOWN : `${elapsed} so far`;
}

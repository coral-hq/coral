import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useRef, useState, type RefObject } from "react";
import { ApiError } from "@/lib/sessionsApi";
import type { RunDetail } from "../api/generated/coralApi";
import { getRun, retryRunRead, runQueryKey } from "../api/runsApi";
import { isFinishedRunStatus } from "../shared/runStatus";
import { useCoralScope } from "../shared/viewerScope";
import type { RunStreamStatus } from "../stream/runStream";
import { detailIsStale, isStalenessTrigger, type StalenessMarks } from "./detailStaleness";

// A run page's detail: the title, spend, target, gates and slots the stream does not carry.
// It is read again every 30 s while the run is unfinished and the page is visible (for
// spend), and when a stream trigger finds it behind the view: at most once per 2 s and one
// read at a time. A mismatch that outlives its reread waits for the next trigger. A page
// that reached a dead end (a 404, or a refused stream) stops the poll.

/** How long a read detail stays fresh. */
export const DETAIL_STALE_MS = 10_000;
/** How often an unfinished run's detail is read again for its spend. */
export const DETAIL_POLL_MS = 30_000;
/** The shortest gap between two rereads a trigger asked for. */
export const DETAIL_REFRESH_MIN_MS = 2_000;

/** What the detail follows of the stream: its triggers, and whether it ended. */
export interface RunDetailStream extends StalenessMarks {
  status?: RunStreamStatus;
}

const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

interface RefreshState {
  /** The page is gone; a reread that ends now asks for nothing more. */
  disposed: boolean;
  previous: StalenessMarks | null;
  /** A trigger came before any detail; the first detail is checked against the view. */
  pendingCheck: boolean;
  inFlight: boolean;
  /** A trigger arrived during a reread; it is checked once that ends. */
  queued: boolean;
  lastStartMs: number;
  timer: ReturnType<typeof setTimeout> | null;
}

/**
 * Run `runId`'s detail for the current viewer, kept in step with `stream`.
 *
 * :param stream: The stream's view and header, whose triggers decide the rereads, and its
 *   status, which ends the poll once the stream says the run is gone or refused.
 */
export function useRunDetail(
  runId: string,
  stream: RunDetailStream,
): UseQueryResult<RunDetail, unknown> {
  const { scope, ready } = useCoralScope();
  const headerStatus = stream.header?.status ?? null;
  const streamEnded = stream.status === "not_found" || stream.status === "failed";
  const detail = useQuery({
    queryKey: runQueryKey(scope, runId),
    queryFn: ({ signal }) => getRun(runId, signal),
    enabled: ready,
    staleTime: DETAIL_STALE_MS,
    retry: retryRunRead,
    // The stream's status first; the detail's own until the stream speaks.
    refetchInterval: (query) =>
      streamEnded ||
      isNotFound(query.state.error) ||
      isFinishedRunStatus(headerStatus ?? query.state.data?.status)
        ? false
        : DETAIL_POLL_MS,
  });

  const latest = useRef({ detail: detail.data, view: stream.view, refetch: detail.refetch });
  // Before the trigger effect below, so a check it makes sees this render's values.
  useEffect(() => {
    latest.current = { detail: detail.data, view: stream.view, refetch: detail.refetch };
  });
  const refresh = useRef<RefreshState>({
    disposed: false,
    previous: null,
    pendingCheck: false,
    inFlight: false,
    queued: false,
    lastStartMs: Number.NEGATIVE_INFINITY,
    timer: null,
  });

  useEffect(() => {
    const state = refresh.current;
    state.disposed = false;
    return () => {
      state.disposed = true;
      if (state.timer !== null) clearTimeout(state.timer);
      state.timer = null;
    };
  }, []);

  useEffect(() => {
    const state = refresh.current;
    const marks: StalenessMarks = { view: stream.view, header: stream.header };
    const triggered = isStalenessTrigger(state.previous, marks);
    state.previous = marks;
    if (triggered) requestReread(state, latest);
  }, [stream.view, stream.header]);

  const loaded = detail.data !== undefined;
  useEffect(() => {
    const state = refresh.current;
    if (!loaded || !state.pendingCheck) return;
    // Only the first detail answers a trigger that came before it; later reads never do.
    state.pendingCheck = false;
    requestReread(state, latest);
  }, [loaded]);

  return detail;
}

/** What a reread checks and calls, as of the last render. */
type Latest = RefObject<{
  detail: RunDetail | undefined;
  view: StalenessMarks["view"];
  refetch: () => Promise<unknown>;
}>;

/** Check the detail now, or once the 2 s gap has passed, or after the reread in flight. */
function requestReread(state: RefreshState, latest: Latest): void {
  if (state.disposed) return;
  if (state.inFlight) {
    state.queued = true;
    return;
  }
  // A check already waiting reads the latest detail and view when it runs.
  if (state.timer !== null) return;
  const waitMs = state.lastStartMs + DETAIL_REFRESH_MIN_MS - Date.now();
  if (waitMs > 0) {
    state.timer = setTimeout(() => {
      state.timer = null;
      rereadIfStale(state, latest);
    }, waitMs);
    return;
  }
  rereadIfStale(state, latest);
}

function rereadIfStale(state: RefreshState, latest: Latest): void {
  const { detail, view, refetch } = latest.current;
  if (detail === undefined) {
    state.pendingCheck = true;
    return;
  }
  if (!detailIsStale(detail, view)) return;
  state.inFlight = true;
  state.lastStartMs = Date.now();
  void refetch().finally(() => {
    state.inFlight = false;
    if (!state.queued) return;
    state.queued = false;
    requestReread(state, latest);
  });
}

/**
 * The detail's failure to show: its latest error, kept while no detail has loaded. A read of
 * a detail that never loaded clears the query's error while it runs; the page keeps showing
 * the failure (and its Retry) until a read succeeds.
 */
export function useDetailFailure(detail: UseQueryResult<RunDetail, unknown>): unknown {
  const { error, data } = detail;
  const [lastError, setLastError] = useState<unknown>(null);
  useEffect(() => {
    if (error !== null) setLastError(error);
    else if (data !== undefined) setLastError(null);
  }, [error, data]);
  if (error !== null) return error;
  return data === undefined ? lastError : null;
}

import { ApiError } from "@/lib/sessionsApi";
import type { RunStreamStatus } from "../stream/runStream";

// Which of its states the run page is in, from its detail read and its stream, and what it
// says about its live updates.

/** The page as a whole: a spinner, one of two dead ends, or the run. */
export type RunPageState = "loading" | "not_found" | "failed" | "ready";

export interface RunPageInputs {
  /**
   * The detail's failure: its latest error, kept while no detail has loaded (a reread clears
   * the query's own error while it runs), `null` while it has none.
   */
  detailError: unknown;
  /** A detail was read (it stays shown when a later read fails). */
  detailLoaded: boolean;
  /** The stream has shown something: a view, a load error or a header. */
  streamShown: boolean;
  streamStatus: RunStreamStatus;
  /** Retry restarted a refused stream, and no frame has come since. */
  streamRetrying: boolean;
}

export const NOT_FOUND_TEXT = "Run not found or you don’t have access";
export const LOAD_FAILED_PAGE_TEXT = "Couldn’t load this run.";

const isNotFound = (error: unknown) => error instanceof ApiError && error.status === 404;

/**
 * The page's state. A 404 from either source ends it (both check the owner). A refused
 * stream, until a frame follows its Retry, or a detail that never loaded, is a failure with
 * Retry. The page waits for the detail or the stream before it shows the run.
 */
export function runPageState({
  detailError,
  detailLoaded,
  streamShown,
  streamStatus,
  streamRetrying,
}: RunPageInputs): RunPageState {
  if (isNotFound(detailError) || streamStatus === "not_found") return "not_found";
  if (streamStatus === "failed" || streamRetrying) return "failed";
  if (detailError !== null && !detailLoaded) return "failed";
  if (!detailLoaded && !streamShown) return "loading";
  return "ready";
}

/** What the page says about its live updates in `status`; nothing while they flow. */
export function connectionNotice(status: RunStreamStatus): string | null {
  switch (status) {
    case "reconnecting":
      return "Reconnecting…";
    case "limited":
      return "Live updates limited";
    case "outdated":
      return "This page is out of date. Reload it for live updates.";
    case "connecting":
    case "live":
    case "paused_hidden":
    case "done":
    case "not_found":
    case "failed":
      return null;
    default: {
      const unhandled: never = status;
      return unhandled;
    }
  }
}

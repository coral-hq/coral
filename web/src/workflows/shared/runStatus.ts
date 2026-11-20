import type { RunStatus } from "../api/runsApi";
import { pauseTitle } from "./pauseCopy";

// The run status pill's text and tone, from the run's status, pause reason and the view's
// open gates. The runs list has no view, so it never shows "Needs you".

export type RunStatusTone = "blue" | "yellow" | "green" | "red" | "gray";

export type RunStatusKind = RunStatus | "needs_you" | "unknown";

export interface RunStatusPillState {
  kind: RunStatusKind;
  text: string;
  tone: RunStatusTone;
}

const STATUSES: Readonly<Record<RunStatus, true>> = {
  starting: true,
  running: true,
  paused: true,
  completed: true,
  failed: true,
  cancelled: true,
};

const isRunStatus = (status: string): status is RunStatus => Object.hasOwn(STATUSES, status);

const pill = (kind: RunStatusKind, text: string, tone: RunStatusTone): RunStatusPillState => ({
  kind,
  text,
  tone,
});

/**
 * The pill for a run: "Needs you" while it runs with a gate open, "Paused: <reason>"
 * while paused (whatever gates it holds), else its status by name.
 *
 * :param openGates: The view's open gates; `null` where no view is known.
 */
export function runStatus(
  status: string,
  pauseReason: string | null,
  openGates: readonly string[] | null,
): RunStatusPillState {
  if (!isRunStatus(status)) return pill("unknown", "Unknown", "gray");
  switch (status) {
    case "starting":
      return pill("starting", "Starting", "blue");
    case "running":
      return openGates !== null && openGates.length > 0
        ? pill("needs_you", "Needs you", "yellow")
        : pill("running", "Running", "blue");
    case "paused":
      return pill("paused", pauseTitle(pauseReason), "yellow");
    case "completed":
      return pill("completed", "Completed", "green");
    case "failed":
      return pill("failed", "Failed", "red");
    case "cancelled":
      return pill("cancelled", "Cancelled", "gray");
    default: {
      const unhandled: never = status;
      return unhandled;
    }
  }
}

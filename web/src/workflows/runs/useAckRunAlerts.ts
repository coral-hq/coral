import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { RunDetail } from "../api/generated/coralApi";
import { WORKFLOW_INBOX_QUERY_KEY } from "../inbox/useWorkflowInbox";
import { ackRunAlerts } from "../inbox/workflowInboxApi";
import { isFinishedRunStatus } from "../shared/runStatus";

// Opening a run marks its low-priority alerts (the plain run-end alert) read, once per
// open page, and only after the detail loaded, which confirms the caller owns the run: at
// once when the run was already finished, else after a `[DONE]` that arrived while open.
// The server never touches the run's other alerts; a failed post is left alone.

/**
 * Mark run `runId`'s low-priority alerts read when the page has seen it finished.
 *
 * :param detail: The run's detail; `undefined` until it loads.
 * :param doneSeen: The stream reached `[DONE]` while this page was open.
 */
export function useAckRunAlerts(
  runId: string,
  detail: RunDetail | undefined,
  doneSeen: boolean,
): void {
  const queryClient = useQueryClient();
  // Whether the first detail this page saw was already finished; `null` until one loads.
  const finishedOnOpen = useRef<boolean | null>(null);
  const posted = useRef(false);
  const loaded = detail !== undefined;
  const finished = loaded && isFinishedRunStatus(detail.status);

  useEffect(() => {
    if (!loaded) return;
    finishedOnOpen.current ??= finished;
    if (posted.current || !(finishedOnOpen.current || doneSeen)) return;
    posted.current = true;
    void ackRunAlerts(runId).then(
      () => queryClient.invalidateQueries({ queryKey: WORKFLOW_INBOX_QUERY_KEY }),
      () => {},
    );
  }, [queryClient, runId, loaded, finished, doneSeen]);
}

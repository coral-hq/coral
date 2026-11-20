import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { InboxKindUi } from "@/lib/inboxKinds";
import { isRetryableRequestError } from "@/lib/queryRetry";
import { ApiError } from "@/lib/sessionsApi";
import type { RunDetail, RunSummary } from "../api/generated/coralApi";
import { getRun, postRunAction, runActionKey, runQueryKey } from "../api/runsApi";
import { CardStatusLine } from "./CardStatusLine";
import { OFFLINE_TEXT, useOnline } from "./useOnline";
import { WORKFLOW_INBOX_QUERY_KEY } from "./useWorkflowInbox";

// Resume and Cancel run on a pause alert's card, offered exactly as the run's
// `allowed_actions` allow. The run is read only while the card is open.

/** How long a read run stays fresh before reopening the card reads it again. */
const RUN_STALE_MS = 10_000;
const UPDATE_FAILED_TEXT = "Couldn’t update the run.";

type CardAction = "resume" | "cancel";

interface Outcome {
  text: string;
  failed: boolean;
}

/** What an accepted action tells the owner, from the run it returned. */
export function runResultText(action: CardAction, run: RunSummary): string {
  if (action === "cancel") return "Cancelled.";
  // A resume that clears one cause of several leaves the run paused for the rest.
  return run.status === "paused" ? "The run is still paused." : "Resumed.";
}

/** What a failed action tells the owner: a conflict in the server's words, else by status. */
export function runActionErrorText(error: unknown): string {
  if (!(error instanceof ApiError)) return UPDATE_FAILED_TEXT;
  // Only Coral's envelope carries a code; without it the message is a bare status line.
  if (error.status === 409 && error.code !== null) return error.message;
  if (error.status === 404) return "This run is no longer available.";
  if (error.status === 503) return "The server is busy; try again.";
  return UPDATE_FAILED_TEXT;
}

/** One retry for a failure a retry can fix; a 404 or another refusal is final. */
const retryRunRead = (failureCount: number, error: unknown) =>
  failureCount < 1 && isRetryableRequestError(error);

/** The run moved on (409) or is gone (404), so its actions are read again. */
const rereadsRun = (error: unknown) =>
  error instanceof ApiError && (error.status === 409 || error.status === 404);

export interface RunActionsProps {
  runId: string;
  /** The card is open; the run is read only then. */
  expanded: boolean;
  ui: InboxKindUi;
  /** The card's own actions, shown after the run's. */
  children: ReactNode;
}

/** The run's status line and action row; Cancel run asks once before it posts. */
export function RunActions({ runId, expanded, ui, children }: RunActionsProps) {
  const queryClient = useQueryClient();
  const online = useOnline();
  const questionId = useId();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const refocusCancel = useRef(false);
  // This card's own request, set at the click so a second click finds the buttons disabled.
  const [pending, setPending] = useState<CardAction | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const run = useQuery({
    queryKey: runQueryKey(runId),
    queryFn: ({ signal }) => getRun(runId, signal),
    enabled: expanded,
    staleTime: RUN_STALE_MS,
    retry: retryRunRead,
  });
  const action = useMutation({
    mutationKey: runActionKey(runId),
    mutationFn: (name: CardAction) => postRunAction(runId, name),
    // Sent at once, as a plain request: never held back until React Query sees the network.
    networkMode: "always",
    // These run even if the card closed meanwhile, so the run and the Inbox still refresh.
    onSuccess: (summary) => {
      // Only what the summary decides; the refetch brings the detail's other fields.
      queryClient.setQueryData<RunDetail>(
        runQueryKey(runId),
        (detail) =>
          detail && { ...detail, status: summary.status, allowed_actions: summary.allowed_actions },
      );
      void queryClient.invalidateQueries({ queryKey: runQueryKey(runId) });
      void queryClient.invalidateQueries({ queryKey: WORKFLOW_INBOX_QUERY_KEY });
    },
    onError: (error) => {
      if (rereadsRun(error)) void queryClient.invalidateQueries({ queryKey: runQueryKey(runId) });
    },
  });
  // A request sent before the card was last closed is still this run's.
  const inFlight = useIsMutating({ mutationKey: runActionKey(runId) }) > 0;
  const busy = pending !== null || inFlight;
  const ready = online && !busy;
  // A failed read hides the buttons: nothing then says what the run allows.
  const allowed = run.isError ? [] : (run.data?.allowed_actions ?? []);
  const canResume = allowed.includes("resume");
  const canCancel = allowed.includes("cancel");
  const confirmWithdrawn = confirming && !canCancel;

  useEffect(() => {
    if (outcome !== null) statusRef.current?.focus();
  }, [outcome]);

  useEffect(() => {
    if (confirming) keepRef.current?.focus();
    else if (refocusCancel.current) cancelRef.current?.focus();
    refocusCancel.current = false;
  }, [confirming]);

  useEffect(() => {
    if (!confirmWithdrawn) return;
    // The run no longer allows a cancel: the question closes for good.
    setConfirming(false);
    const focused = document.activeElement;
    if (focused === null || focused === document.body) statusRef.current?.focus();
  }, [confirmWithdrawn]);

  const perform = (name: CardAction) => {
    if (!ready) return;
    setPending(name);
    // Cleared first, so the same text again is announced again.
    setOutcome(null);
    action.mutate(name, {
      onSuccess: (summary) => setOutcome({ text: runResultText(name, summary), failed: false }),
      onError: (error) => setOutcome({ text: runActionErrorText(error), failed: true }),
      onSettled: () => {
        setPending(null);
        setConfirming(false);
      },
    });
  };

  const askToCancel = () => {
    if (ready) setConfirming(true);
  };

  const keepRunning = () => {
    refocusCancel.current = true;
    setConfirming(false);
  };

  const onConfirmKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !busy) keepRunning();
  };

  const showConfirm = confirming && canCancel;
  return (
    <>
      <CardStatusLine
        ref={statusRef}
        message={outcome?.text ?? null}
        failed={outcome?.failed === true}
        notice={online ? null : OFFLINE_TEXT}
      />
      {showConfirm && (
        <div
          role="group"
          aria-labelledby={questionId}
          onKeyDown={onConfirmKeyDown}
          className="flex flex-col gap-1"
        >
          <p id={questionId} className="text-sm">
            Cancel this run? Its steps stop.
          </p>
          <ui.InboxActions>
            <Button
              variant="destructive"
              size="xs"
              loading={pending === "cancel"}
              disabled={!ready}
              onClick={() => perform("cancel")}
              componentId="inbox.workflow_alert.confirm_cancel"
            >
              Cancel run
            </Button>
            <Button
              ref={keepRef}
              variant="outline"
              size="xs"
              className={ui.outlineAction}
              disabled={busy}
              onClick={keepRunning}
              componentId="inbox.workflow_alert.keep_running"
            >
              Keep running
            </Button>
          </ui.InboxActions>
        </div>
      )}
      <ui.InboxActions>
        {!showConfirm && canResume && (
          <Button
            size="xs"
            className={ui.primaryAction}
            loading={pending === "resume"}
            disabled={!ready}
            onClick={() => perform("resume")}
            componentId="inbox.workflow_alert.resume"
          >
            Resume
          </Button>
        )}
        {!showConfirm && canCancel && (
          <Button
            ref={cancelRef}
            variant="outline"
            size="xs"
            className={ui.outlineAction}
            disabled={!ready}
            onClick={askToCancel}
            componentId="inbox.workflow_alert.cancel"
          >
            Cancel run
          </Button>
        )}
        {children}
      </ui.InboxActions>
    </>
  );
}

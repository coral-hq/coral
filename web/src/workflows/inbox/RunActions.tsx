import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import type { InboxKindUi } from "@/lib/inboxKinds";
import { ApiError } from "@/lib/sessionsApi";
import type { RunDetail, RunSummary } from "../api/generated/coralApi";
import {
  getRun,
  postRunAction,
  retryRunRead,
  runActionKey,
  runQueryKey,
  type RunAction,
} from "../api/runsApi";
import { useCoralScope } from "../shared/viewerScope";
import { CardStatusLine } from "./CardStatusLine";
import { OFFLINE_TEXT, useOnline } from "./useOnline";
import { WORKFLOW_INBOX_QUERY_KEY } from "./useWorkflowInbox";

// Resume and Cancel run on a pause alert's card, offered exactly as the run's
// `allowed_actions` allow. The run is read only while the card is open. The run
// view passes the actions its stream allows, and offers Pause too.

/** How long a read run stays fresh before reopening the card reads it again. */
const RUN_STALE_MS = 10_000;
const UPDATE_FAILED_TEXT = "Couldn’t update the run.";
const NO_ACTIONS: readonly RunAction[] = Object.freeze([]);

interface Outcome {
  text: string;
  failed: boolean;
}

/** What an accepted action tells the owner, from the run it returned. */
export function runResultText(action: RunAction, run: RunSummary): string {
  if (action === "cancel") return "Cancelled.";
  if (action === "pause") return "Paused.";
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

/** The run moved on (409) or is gone (404), so its actions are read again. */
const rereadsRun = (error: unknown) =>
  error instanceof ApiError && (error.status === 409 || error.status === 404);

interface RunActionsBaseProps {
  runId: string;
  ui: InboxKindUi;
  /** Offer Pause when the run allows it. */
  withPause?: boolean;
  /** The buttons' component ids are `<prefix>.<button>`. */
  componentIdPrefix?: string;
  /** The card's own actions, shown after the run's. */
  children?: ReactNode;
}

/** The actions come from a read of the run, made only while the card is open. */
interface ReadRunActionsProps extends RunActionsBaseProps {
  expanded: boolean;
  allowed?: undefined;
}

/** The actions come from the caller's view of the run, which is never read here. */
interface GivenRunActionsProps extends RunActionsBaseProps {
  expanded?: boolean;
  allowed: readonly RunAction[];
}

export type RunActionsProps = ReadRunActionsProps | GivenRunActionsProps;

/** The run's status line and action row; Cancel run asks once before it posts. */
export function RunActions({
  runId,
  expanded = true,
  ui,
  allowed,
  withPause = false,
  componentIdPrefix = "inbox.workflow_alert",
  children,
}: RunActionsProps) {
  const queryClient = useQueryClient();
  const { scope, ready: viewerKnown } = useCoralScope();
  const runKey = runQueryKey(scope, runId);
  const actionKey = runActionKey(scope, runId);
  const online = useOnline();
  const questionId = useId();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const keepRef = useRef<HTMLButtonElement>(null);
  const refocusCancel = useRef(false);
  // This card's own request, set at the click so a second click finds the buttons disabled.
  const [pending, setPending] = useState<RunAction | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const run = useQuery({
    queryKey: runKey,
    queryFn: ({ signal }) => getRun(runId, signal),
    enabled: expanded && viewerKnown && allowed === undefined,
    staleTime: RUN_STALE_MS,
    retry: retryRunRead,
  });
  const action = useMutation({
    mutationKey: actionKey,
    mutationFn: (name: RunAction) => postRunAction(runId, name),
    // Sent at once, as a plain request: never held back until React Query sees the network.
    networkMode: "always",
    // These run even if the card closed meanwhile, so the run and the Inbox still refresh.
    onSuccess: (summary) => {
      // Only what the summary decides; the refetch brings the detail's other fields.
      queryClient.setQueryData<RunDetail>(
        runKey,
        (detail) =>
          detail && { ...detail, status: summary.status, allowed_actions: summary.allowed_actions },
      );
      void queryClient.invalidateQueries({ queryKey: runKey });
      void queryClient.invalidateQueries({ queryKey: WORKFLOW_INBOX_QUERY_KEY });
    },
    onError: (error) => {
      if (rereadsRun(error)) void queryClient.invalidateQueries({ queryKey: runKey });
    },
  });
  // A request sent before the card was last closed is still this run's.
  const inFlight = useIsMutating({ mutationKey: actionKey }) > 0;
  const busy = pending !== null || inFlight;
  // The viewer's arrival re-keys the action, which would drop a request sent before it.
  const ready = online && !busy && viewerKnown;
  // A failed read hides the buttons: nothing then says what the run allows.
  const offered = allowed ?? (run.isError ? NO_ACTIONS : (run.data?.allowed_actions ?? NO_ACTIONS));
  const canPause = withPause && offered.includes("pause");
  const canResume = offered.includes("resume");
  const canCancel = offered.includes("cancel");
  const componentId = (button: string) => `${componentIdPrefix}.${button}`;
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

  const perform = (name: RunAction) => {
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
              componentId={componentId("confirm_cancel")}
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
              componentId={componentId("keep_running")}
            >
              Keep running
            </Button>
          </ui.InboxActions>
        </div>
      )}
      <ui.InboxActions>
        {!showConfirm && canPause && (
          <Button
            variant="outline"
            size="xs"
            className={ui.outlineAction}
            loading={pending === "pause"}
            disabled={!ready}
            onClick={() => perform("pause")}
            componentId={componentId("pause")}
          >
            Pause
          </Button>
        )}
        {!showConfirm && canResume && (
          <Button
            size="xs"
            className={ui.primaryAction}
            loading={pending === "resume"}
            disabled={!ready}
            onClick={() => perform("resume")}
            componentId={componentId("resume")}
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
            componentId={componentId("cancel")}
          >
            Cancel run
          </Button>
        )}
        {children}
      </ui.InboxActions>
    </>
  );
}

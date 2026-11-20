import { useQuery } from "@tanstack/react-query";
import { CircleAlertIcon } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { PageScroll } from "@/components/PageScroll";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useParams } from "@/lib/routing";
import { getRunGraph, retryRunRead, runGraphQueryKey } from "../api/runsApi";
import { RunActions } from "../inbox/RunActions";
import { LOAD_FAILED_TEXT } from "../shared/pauseCopy";
import { useCoralScope } from "../shared/viewerScope";
import type { RunStreamStatus } from "../stream/runStream";
import { useRunStream } from "../stream/useRunStream";
import type { StalenessMarks } from "./detailStaleness";
import { runViewCardUi } from "./gateCardUi";
import { PauseBanner } from "./PauseBanner";
import { RunHeaderBar } from "./RunHeaderBar";
import {
  connectionNotice,
  LOAD_FAILED_PAGE_TEXT,
  NOT_FOUND_TEXT,
  runPageState,
  type RunPageState,
} from "./runPageState";
import { useAckRunAlerts } from "./useAckRunAlerts";
import { useDetailFailure, useRunDetail } from "./useRunDetail";

// The live view of one run at `/workflows/runs/:runId`. Its status, pause reason, causes
// and allowed actions come only from the stream's header and view; the detail supplies the
// title, spend, gates and slots. Before the stream's first frame the detail's status shows
// as provisional, with no actions.

export function RunPage() {
  const { runId = "" } = useParams<{ runId: string }>();
  const { scope } = useCoralScope();
  // Another run, or another viewer, is a new page: its stream, rereads and alert marking
  // start over.
  return <RunPageBody key={`${scope}\u0000${runId}`} runId={runId} />;
}

function RunPageBody({ runId }: { runId: string }) {
  const { scope, ready } = useCoralScope();
  const [doneSeen, setDoneSeen] = useState(false);
  const [streamAttempt, setStreamAttempt] = useState(0);
  // The stream's view and header when Retry restarted it: they are not news until a frame
  // replaces them.
  const [retriedFrom, setRetriedFrom] = useState<StalenessMarks | null>(null);
  const statusRef = useRef<HTMLDivElement>(null);
  const onDone = useCallback(() => setDoneSeen(true), []);
  const stream = useRunStream(runId, { onDone, restartKey: streamAttempt });
  const detail = useRunDetail(runId, stream);
  const detailFailure = useDetailFailure(detail);
  const graph = useQuery({
    queryKey: runGraphQueryKey(scope, runId),
    queryFn: ({ signal }) => getRunGraph(runId, signal),
    enabled: ready,
    // A run's graph is pinned when it starts and never changes.
    staleTime: Infinity,
    retry: retryRunRead,
  });
  useAckRunAlerts(runId, detail.data, doneSeen);

  const { header, view, viewError } = stream;
  const state = runPageState({
    detailError: detailFailure,
    detailLoaded: detail.data !== undefined,
    streamShown: view !== null || viewError !== null || header !== null,
    streamStatus: stream.status,
    streamRetrying:
      retriedFrom !== null && view === retriedFrom.view && header === retriedFrom.header,
  });

  // Leaving the failed state unmounts Retry; focus moves to the run's status, not the body.
  const previousState = useRef(state);
  useEffect(() => {
    const left = previousState.current === "failed" && state === "ready";
    previousState.current = state;
    const focused = document.activeElement;
    if (left && (focused === null || focused === document.body)) statusRef.current?.focus();
  }, [state]);

  const retry = (): void => {
    if (stream.status === "failed") {
      setRetriedFrom({ view, header });
      setStreamAttempt((attempt) => attempt + 1);
    }
    if (detail.data === undefined) void detail.refetch();
  };

  const run = detail.data;
  const title = run?.title ?? graph.data?.name ?? "Workflow run";
  if (state !== "ready") {
    return (
      <RunPageFrame state={state} streamStatus={stream.status}>
        <CoralPageHeader title={state === "not_found" ? "Workflow run" : title} />
        <div className="flex flex-col items-center gap-3 py-16 text-center">
          <div role="status" aria-live="polite" data-testid="run-page-message">
            {state === "loading" ? (
              <Spinner
                role="img"
                className="size-5 text-muted-foreground"
                aria-label="Loading run"
              />
            ) : (
              <p className="text-muted-foreground text-ui">
                {state === "not_found" ? NOT_FOUND_TEXT : LOAD_FAILED_PAGE_TEXT}
              </p>
            )}
          </div>
          {state === "failed" && (
            <Button variant="outline" onClick={retry} componentId="workflows.run.retry">
              Retry
            </Button>
          )}
        </div>
      </RunPageFrame>
    );
  }

  const status = header?.status ?? run?.status ?? "starting";
  const loadFailed = viewError ?? header?.load_error ?? null;
  const allowed = header?.allowed_actions ?? [];
  // Nothing but a cancel can act on a run the engine cannot read.
  const offered = loadFailed === null ? allowed : allowed.filter((action) => action === "cancel");
  const settingUp = status === "starting" && (view === null || view.activations.length === 0);
  return (
    <RunPageFrame state={state} streamStatus={stream.status}>
      <RunHeaderBar
        title={title}
        status={status}
        pauseReason={header ? header.pause_reason : (run?.pause_reason ?? null)}
        openGates={header ? (view?.open_gates ?? null) : null}
        provisional={header === null}
        createdAt={run?.created_at ?? null}
        finishedAt={header ? header.finished_at : (run?.finished_at ?? null)}
        spend={run?.spend}
        notice={connectionNotice(stream.status)}
        statusRef={statusRef}
        actions={
          header === null ? null : (
            <div className="flex flex-col items-end gap-1">
              <RunActions
                runId={runId}
                ui={runViewCardUi}
                allowed={offered}
                withPause
                componentIdPrefix="workflows.run"
              />
            </div>
          )
        }
      />
      <div className="flex flex-col gap-4">
        {loadFailed !== null && (
          <p
            data-testid="run-load-failed"
            className="flex items-center gap-2 rounded-xl border border-border p-4 text-ui"
          >
            <CircleAlertIcon aria-hidden className="size-4 shrink-0 text-destructive" />
            {LOAD_FAILED_TEXT}
          </p>
        )}
        {loadFailed === null && header?.status === "paused" && (
          <PauseBanner reason={header.pause_reason} view={view} graph={graph.data ?? null} />
        )}
        {settingUp && <p className="text-ui text-muted-foreground">Setting up the run…</p>}
      </div>
    </RunPageFrame>
  );
}

function RunPageFrame({
  state,
  streamStatus,
  children,
}: {
  state: RunPageState;
  streamStatus: RunStreamStatus;
  children: ReactNode;
}) {
  return (
    <PageScroll maxWidthClassName="max-w-[1200px]" contentClassName="px-4 md:px-10">
      <div data-testid="workflow-run-page" data-state={state} data-stream={streamStatus}>
        {children}
      </div>
    </PageScroll>
  );
}

import { useQuery } from "@tanstack/react-query";
import { CircleAlertIcon } from "lucide-react";
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { PageScroll } from "@/components/PageScroll";
import { RenderErrorBoundary } from "@/components/RenderErrorBoundary";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useLocation, useNavigate, useParams, useSearchParams } from "@/lib/routing";
import { getRunGraph, retryRunRead, runGraphQueryKey } from "../api/runsApi";
import { FlowCanvas } from "../canvas/FlowCanvas";
import { runOverlay } from "../canvas/runOverlay";
import { RunActions } from "../inbox/RunActions";
import { runPath } from "../nav/coralPaths";
import { LOAD_FAILED_TEXT } from "../shared/pauseCopy";
import { isFinishedRunStatus } from "../shared/runStatus";
import { useCoralScope } from "../shared/viewerScope";
import type { RunStreamStatus } from "../stream/runStream";
import { useRunStream } from "../stream/useRunStream";
import type { StalenessMarks } from "./detailStaleness";
import { runViewCardUi } from "./gateCardUi";
import { PauseBanner } from "./PauseBanner";
import { RunGatePanel, type GateFocus } from "./RunGatePanel";
import { RunHeaderBar } from "./RunHeaderBar";
import { findSessionChip, RunNodePanel } from "./RunNodePanel";
import {
  connectionNotice,
  LOAD_FAILED_PAGE_TEXT,
  NOT_FOUND_TEXT,
  runPageState,
  type RunPageState,
} from "./runPageState";
import { RunStepList } from "./RunStepList";
import { useAckRunAlerts } from "./useAckRunAlerts";
import { useDetailFailure, useRunDetail } from "./useRunDetail";
import { OutcomePanel } from "./outcome/OutcomePanel";
import { runSession, stepSessions } from "./agents/stepSessions";
import { StepDrawerFallback } from "./agents/StepDrawerFallback";

// Split from the page. The app shell already bundles the transcript's modules, so this
// saves no download in the app; the page alone (as its route tests mount it) skips them.
const StepDrawer = lazy(() =>
  import("./agents/StepDrawer").then((module) => ({ default: module.StepDrawer })),
);

// The live view of one run at `/workflows/runs/:runId`. Its status, pause reason, causes
// and allowed actions come only from the stream's header and view; the detail supplies the
// title, spend, gates and slots. Before the stream's first frame the detail's status shows
// as provisional, with no actions. The selected node rides `?node=`; `?panel=gate` asks to
// show that node's open gate; `?agent=` opens a step session's transcript in a drawer. A
// finished run shows its outcome.

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
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const overlay = useMemo(
    () => (graph.data && view ? runOverlay(graph.data, view) : null),
    [graph.data, view],
  );
  const nodeParam = searchParams.get("node");
  // Only a node the graph holds is selected; a stale link selects nothing.
  const selectedNodeId = nodeParam !== null && overlay?.has(nodeParam) ? nodeParam : null;
  const showGate = searchParams.get("panel") === "gate";
  const gateFocus = useMemo<GateFocus | null>(
    () =>
      showGate && selectedNodeId !== null ? { nodeId: selectedNodeId, key: location.key } : null,
    [showGate, selectedNodeId, location.key],
  );
  // Selecting the selected step again adds no history entry.
  const selectNode = useCallback(
    (nodeId: string) => {
      if (nodeId !== selectedNodeId) void navigate(runPath(runId, { node: nodeId }));
    },
    [navigate, runId, selectedNodeId],
  );
  // `?agent=` is untrusted: the drawer opens only a session the run's own slots list.
  const agentParam = searchParams.get("agent");
  const run = detail.data;
  const openSessionId =
    run && agentParam !== null
      ? (runSession(run, graph.data ?? null, agentParam)?.sessionId ?? null)
      : null;
  const closeDrawer = useCallback(
    () => void navigate(runPath(runId, { node: selectedNodeId ?? undefined })),
    [navigate, runId, selectedNodeId],
  );
  const refetchDetail = detail.refetch;
  const onAnswerSettled = useCallback(() => void refetchDetail(), [refetchDetail]);
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
            <div data-testid="run-actions" className="flex flex-col items-end gap-1">
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
        {isFinishedRunStatus(status) && <OutcomePanel runId={runId} />}
        {run && (
          <RunGatePanel
            runId={runId}
            detail={run}
            view={view}
            graph={graph.data ?? null}
            selectedNodeId={selectedNodeId}
            focus={gateFocus}
            onAnswerSettled={onAnswerSettled}
            focusFallback={statusRef}
          />
        )}
        {graph.data && overlay && (
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div
              data-testid="run-canvas"
              className="h-[360px] overflow-hidden rounded-xl border border-border md:h-[460px]"
            >
              {/* A graph the layout cannot place leaves the steps, gates and actions working. */}
              <RenderErrorBoundary name="the run's graph" resetKey={graph.data.content_hash}>
                <FlowCanvas
                  compiled={graph.data}
                  overlay={overlay}
                  selectedNodeId={selectedNodeId}
                  onSelectNode={selectNode}
                />
              </RenderErrorBoundary>
            </div>
            <div className="flex min-w-0 flex-col gap-4">
              <RunStepList
                graph={graph.data}
                overlay={overlay}
                selectedNodeId={selectedNodeId}
                onSelectNode={selectNode}
              />
              {selectedNodeId !== null && (
                <RunNodePanel
                  graph={graph.data}
                  nodeId={selectedNodeId}
                  overlay={overlay.get(selectedNodeId) ?? null}
                  runId={runId}
                  sessions={run ? stepSessions(run, graph.data, selectedNodeId, view) : []}
                  openSessionId={openSessionId}
                />
              )}
            </div>
          </div>
        )}
      </div>
      {run && agentParam !== null && (
        <Suspense fallback={<StepDrawerFallback />}>
          <StepDrawer
            detail={run}
            graph={graph.data ?? null}
            view={view}
            agent={agentParam}
            onClose={closeDrawer}
            findOpener={findSessionChip}
            focusFallback={statusRef}
          />
        </Suspense>
      )}
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

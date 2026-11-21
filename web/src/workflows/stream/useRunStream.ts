import { skipToken, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { authenticatedFetch } from "@/lib/identity";
import { awaitReconnectDelay, isPageHidden } from "@/lib/reconnectBackoff";
import { conversationRegistry, type ConversationRegistry } from "@/store/conversationRegistry";
import { getStreamSlotManager } from "@/store/streamSlots";
import { getRun, runQueryKey, runViewQueryKey } from "../api/runsApi";
import { useCoralScope } from "../shared/viewerScope";
import {
  abortableSleep,
  startRunStream,
  type RunStreamDeps,
  type RunStreamState,
} from "./runStream";

// A run page's live view: each mounted hook runs one stream controller for (viewer scope,
// run) and writes its every state under `["coral-run-view", scope, runId]`, the key's only
// writer. A remount within the cache time resumes from it with `Last-Event-ID`.

/** How long a run's streamed view stays cached once no page shows it. */
export const RUN_VIEW_GC_MS = 5 * 60_000;

const NOT_STARTED: RunStreamState = {
  view: null,
  viewError: null,
  header: null,
  seq: null,
  status: "connecting",
};

/**
 * Dispose this tab's least recently viewed background chat, so its stream frees a slot. The
 * registry never takes the conversation on screen, a retained one (an open drawer's session)
 * or one holding unsent work.
 */
export function evictBackgroundChat(
  registry: ConversationRegistry = conversationRegistry,
): boolean {
  return registry.evictLruEvictable() !== null;
}

const documentVisibility: RunStreamDeps["visibility"] = {
  hidden: isPageHidden,
  subscribe: (onChange) => {
    document.addEventListener("visibilitychange", onChange);
    return () => document.removeEventListener("visibilitychange", onChange);
  },
};

function runStreamDeps(queryClient: QueryClient, scope: string, runId: string): RunStreamDeps {
  return {
    fetch: authenticatedFetch,
    slots: getStreamSlotManager,
    evictBackgroundChat: () => evictBackgroundChat(),
    // Into the detail's own key, so the page's detail shows what limited mode read. The
    // controller's signal ends the request, so a hide, a stop or a hung read never waits on it.
    readDetail: (signal) =>
      getRun(runId, signal).then((detail) => {
        if (!signal.aborted) queryClient.setQueryData(runQueryKey(scope, runId), detail);
        return detail;
      }),
    waitBackoff: awaitReconnectDelay,
    sleep: abortableSleep,
    visibility: documentVisibility,
  };
}

export interface UseRunStreamOptions {
  /** Called once when the stream reaches `[DONE]` while this hook is mounted. */
  onDone?: () => void;
  /** A new value starts the stream again from its cached state, as Retry does after a refusal. */
  restartKey?: number;
}

/**
 * The live view of run `runId` for the current viewer. Nothing starts until the viewer is
 * known. On `[DONE]` the run's detail is invalidated and `onDone` is called.
 * Call it once per run page: each call holds its own stream slot.
 */
export function useRunStream(runId: string, options: UseRunStreamOptions = {}): RunStreamState {
  const queryClient = useQueryClient();
  const { scope, ready } = useCoralScope();
  const cached = useQuery<RunStreamState>({
    queryKey: runViewQueryKey(scope, runId),
    queryFn: skipToken,
    staleTime: Infinity,
    gcTime: RUN_VIEW_GC_MS,
    // The controller already shares unchanged parts. Structural sharing would rebuild the
    // view with `copy[key] = …`, turning an own `__proto__` member into a prototype.
    structuralSharing: false,
  });
  const { restartKey = 0 } = options;
  const onDone = useRef(options.onDone);
  useEffect(() => {
    onDone.current = options.onDone;
  });

  useEffect(() => {
    if (!ready) return undefined;
    const viewKey = runViewQueryKey(scope, runId);
    const seed = queryClient.getQueryData<RunStreamState>(viewKey) ?? null;
    const deps = runStreamDeps(queryClient, scope, runId);
    return startRunStream(runId, seed, deps, (state) => {
      queryClient.setQueryData(viewKey, state);
      // The controller reports `done` once, then stops.
      if (state.status !== "done") return;
      // The outcome is read only once the run finished, so `[DONE]` cannot make it stale.
      void queryClient.invalidateQueries({ queryKey: runQueryKey(scope, runId) });
      onDone.current?.();
    });
  }, [queryClient, scope, ready, runId, restartKey]);

  return cached.data ?? NOT_STARTED;
}

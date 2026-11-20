import { useEffect, useRef } from "react";
import type { Conversation } from "@/hooks/useConversations";
import { showNotification } from "@/lib/browserNotifications";
import { useLocation, useNavigate, useRebasePath } from "@/lib/routing";
import { getSession } from "@/lib/sessionsApi";
import type { WorkflowAlert } from "../api/types";
import { isWorkflowGateEvent } from "../inbox/workflowEntries";
import { runPath } from "../nav/coralPaths";
import { isRunAnchor, runIdOf } from "../session/coralLabels";

// One OS notification per run event while the app is open. The generic idle
// notifier stays silent for run sessions (the workflow kind silences them), so
// this covers gates, step prompts mirrored onto the anchor, and other alerts.
//
// - A gate notifies once, from its alert: never from the anchor's pending count,
//   which also holds step prompts and can be first seen with the gate in it.
// - A step prompt notifies once by its elicitation id, read from the anchor's
//   snapshot when the anchor's count rises; gate prompts there are left to alerts.
// - Other new alerts (pause, watchdog, run end) notify at most once per run per
//   10 minutes, so a run that pauses over and over does not flood the owner.

const INBOX_PATH = "/inbox";
const PROMPTLESS_INTERVAL_MS = 10 * 60_000;
const STEP_PROMPT_BODY = "A step is waiting for your input.";

interface NotifierState {
  /** Viewer and server the state belongs to; another one starts over. */
  scope: string;
  /** Anchor id → its pending count when last seen. */
  counts: Map<string, number>;
  /** Anchors whose prompts were read once; their later new prompts notify. */
  synced: Set<string>;
  /** Step prompt ids already known (at a baseline, or notified). */
  seenPrompts: Set<string>;
  /** Anchor id → its snapshot reads, one after another. */
  reads: Map<string, Promise<void>>;
  /** Alert ids seen so far; `null` until the feed first loads. */
  seenAlerts: Set<string> | null;
  /** Run id → when its last non-gate alert notified (ms). */
  lastPromptless: Map<string, number>;
}

interface RunEvent {
  runId: string;
  anchorId: string | null;
  title: string;
  body: string;
}

function freshState(scope: string): NotifierState {
  return {
    scope,
    counts: new Map(),
    synced: new Set(),
    seenPrompts: new Set(),
    reads: new Map(),
    seenAlerts: null,
    lastPromptless: new Map(),
  };
}

function isWindowFocused(): boolean {
  return typeof document.hasFocus === "function" ? document.hasFocus() : true;
}

/** Window focus from focus and blur events (and any interaction), like the idle notifier. */
function useWindowFocusRef() {
  const focused = useRef(isWindowFocused());
  useEffect(() => {
    const onFocus = () => {
      focused.current = true;
    };
    const onBlur = () => {
      focused.current = false;
    };
    window.addEventListener("focus", onFocus);
    window.addEventListener("blur", onBlur);
    window.addEventListener("pointerdown", onFocus);
    window.addEventListener("keydown", onFocus);
    return () => {
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("pointerdown", onFocus);
      window.removeEventListener("keydown", onFocus);
    };
  }, []);
  return focused;
}

/** New alerts as run events: every new gate, and other alerts within the per-run limit. */
function alertEvents(
  state: NotifierState,
  alerts: readonly WorkflowAlert[],
  now: number,
): Map<string, RunEvent> {
  const events = new Map<string, RunEvent>();
  if (state.seenAlerts === null) {
    state.seenAlerts = new Set(alerts.map((alert) => alert.alert_id));
    return events;
  }
  for (const alert of alerts) {
    if (state.seenAlerts.has(alert.alert_id)) continue;
    state.seenAlerts.add(alert.alert_id);
    const gate = alert.kind === "gate";
    if (!gate) {
      const last = state.lastPromptless.get(alert.run_id);
      if (last !== undefined && now - last < PROMPTLESS_INTERVAL_MS) continue;
      state.lastPromptless.set(alert.run_id, now);
    }
    // One notification per run per update; a gate says more than a pause.
    if (events.has(alert.run_id) && !gate) continue;
    events.set(alert.run_id, {
      runId: alert.run_id,
      anchorId: alert.session_id,
      title: alert.run_title,
      body: `${alert.title}: ${alert.message}`,
    });
  }
  return events;
}

/**
 * Notify run events while the app is open, tagged `coral:run:<run_id>` and opening
 * the Inbox. The first look at the feed, and at each anchor's prompts, is the
 * baseline; nothing notifies while the Inbox, the run's page or its anchor is
 * open in a focused window.
 *
 * :param alerts: The workflow feed, or `undefined` until it first loads.
 * :param rows: Loaded session rows with the server's pending counts.
 * :param scope: The viewer and server; a change forgets everything seen.
 */
export function useWorkflowRunNotifications(
  enabled: boolean,
  alerts: readonly WorkflowAlert[] | undefined,
  rows: readonly Conversation[],
  scope: string,
): void {
  const navigate = useNavigate();
  const rebasePath = useRebasePath();
  const { pathname } = useLocation();
  const focused = useWindowFocusRef();
  const latest = useRef({ navigate, rebasePath, pathname, alerts });
  latest.current = { navigate, rebasePath, pathname, alerts };
  const stateRef = useRef<NotifierState>(freshState(scope));

  useEffect(() => {
    if (!enabled || stateRef.current.scope !== scope) stateRef.current = freshState(scope);
    if (!enabled) return;
    const state = stateRef.current;

    const notify = (event: RunEvent) => {
      const { navigate: go, rebasePath: rebase, pathname: path } = latest.current;
      const watching =
        focused.current &&
        (path === rebase(INBOX_PATH) ||
          path === rebase(runPath(event.runId)) ||
          (event.anchorId !== null && path === rebase(`/c/${event.anchorId}`)));
      if (watching) return;
      showNotification({
        title: event.title,
        body: event.body,
        tag: `coral:run:${event.runId}`,
        onClick: () => go(INBOX_PATH),
        navigatePath: INBOX_PATH,
      });
    };

    /** Read the anchor's prompts; new step prompts notify unless this is its first read. */
    const readPrompts = async (row: Conversation, runId: string) => {
      let pending: Record<string, unknown>[];
      try {
        pending = (await getSession(row.id)).pendingElicitations ?? [];
      } catch {
        return; // Read again on the anchor's next rise.
      }
      if (stateRef.current !== state) return;
      const baseline = !state.synced.has(row.id);
      state.synced.add(row.id);
      let fresh = false;
      for (const event of pending) {
        const id = event.elicitation_id;
        if (typeof id !== "string" || isWorkflowGateEvent({ row, event })) continue;
        if (state.seenPrompts.has(id)) continue;
        state.seenPrompts.add(id);
        fresh = true;
      }
      if (baseline || !fresh) return;
      const runTitle = latest.current.alerts?.find((alert) => alert.run_id === runId)?.run_title;
      notify({
        runId,
        anchorId: row.id,
        title: runTitle ?? row.title ?? "Workflow run",
        body: STEP_PROMPT_BODY,
      });
    };

    for (const row of rows) {
      const runId = runIdOf(row);
      if (runId === null || !isRunAnchor(row) || row.archived) continue;
      const count = row.pending_elicitations_count ?? 0;
      const prior = state.counts.get(row.id);
      state.counts.set(row.id, count);
      if (prior === undefined && count === 0) {
        state.synced.add(row.id); // Nothing pending: every later prompt is new.
        continue;
      }
      if (prior !== undefined && count <= prior) continue;
      const previous = state.reads.get(row.id) ?? Promise.resolve();
      state.reads.set(
        row.id,
        previous.then(() => readPrompts(row, runId)),
      );
    }

    if (alerts !== undefined) {
      for (const event of alertEvents(state, alerts, Date.now()).values()) notify(event);
    }
  }, [enabled, alerts, rows, scope, focused]);
}

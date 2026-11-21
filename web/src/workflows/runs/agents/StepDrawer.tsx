import { MessagesSquareIcon, XIcon } from "lucide-react";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type MouseEvent,
  type RefObject,
} from "react";
import { createPortal } from "react-dom";
import { SideChatPane } from "@/components/chat/SideChatPane";
import { RenderErrorBoundary } from "@/components/RenderErrorBoundary";
import { Button } from "@/components/ui/button";
import { isFocusInDialogOrMenu, isKeyOwningOverlayOpen, isTextEntry } from "@/lib/hotkeys";
import { Link } from "@/lib/routing";
import { cn } from "@/lib/utils";
import { releaseConversation, useChatStore } from "@/store/chatStore";
import { conversationRegistry } from "@/store/conversationRegistry";
import type { CompiledGraph, RunDetail, RunView } from "../../api/generated/coralApi";
import { nodeLabel } from "../../shared/pauseCopy";
import { RosterChip } from "../../shared/RosterChip";
import { DRAWER_PANEL_CLASS, drawerRoot } from "./StepDrawerFallback";
import { agentName, runSession, slotStatusLine } from "./stepSessions";

// A read-only transcript of one step's session beside the run, opened by `?agent=`. The
// URL stays on the run, so AppShell never enters chat mode. While open, the drawer keeps
// its session's stream from being evicted; closing it gives back only a stream it opened
// itself, and none the person took to its Chat page, which binds the same stream at once.

export const NOT_IN_RUN_TEXT = "This session isn’t part of this run.";

export interface StepDrawerProps {
  detail: RunDetail;
  graph: CompiledGraph | null;
  /** The stream's view, for the slot's live status. */
  view: RunView | null;
  /** `?agent=` as the URL holds it: untrusted until the run's slots list it. */
  agent: string;
  /** Leave the drawer: the run page pushes its URL without `agent`. */
  onClose: () => void;
  /** The control that opens this session's drawer, which takes focus back on close. */
  findOpener?: (sessionId: string) => HTMLElement | null;
  /** Where focus goes on close when no opener is on the page. */
  focusFallback?: RefObject<HTMLElement | null>;
}

export function StepDrawer({
  detail,
  graph,
  view,
  agent,
  onClose,
  findOpener,
  focusFallback,
}: StepDrawerProps) {
  const session = runSession(detail, graph, agent, view);
  const sessionId = session?.sessionId ?? null;
  const headingId = useId();
  const panelRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  // The session whose "Open in Chat" was followed in place, which keeps its stream.
  const followed = useRef<string | null>(null);
  const wasFollowed = useCallback((id: string) => followed.current === id, []);

  // Focus moves in once per opening; a reread that changes the content leaves it be.
  useEffect(() => headingRef.current?.focus({ preventScroll: true }), []);

  // However the drawer closes (Close, Escape, Back, another step), focus inside it goes
  // back to the control that opened it, else to the page. A layout cleanup runs while the
  // panel is still in the document, so it can still tell where focus is.
  const focusReturn = useRef({ sessionId, findOpener, focusFallback });
  useLayoutEffect(() => {
    focusReturn.current = { sessionId, findOpener, focusFallback };
  });
  useLayoutEffect(() => {
    const panel = panelRef.current;
    return () => {
      if (!panel?.contains(document.activeElement)) return;
      const { sessionId: last, findOpener: opener, focusFallback: fallback } = focusReturn.current;
      const target = (last === null ? null : opener?.(last)) ?? fallback?.current ?? null;
      target?.focus();
    };
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      // A dialog, menu or fullscreen view keeps its Escape; so does text being typed.
      if (isFocusInDialogOrMenu() || isKeyOwningOverlayOpen(panelRef.current)) return;
      if (event.target instanceof HTMLElement && isTextEntry(event.target)) return;
      onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const onFollow = (event: MouseEvent<HTMLAnchorElement>) => {
    const modified = event.metaKey || event.ctrlKey || event.shiftKey || event.altKey;
    if (event.button === 0 && !modified) followed.current = sessionId;
  };
  const status = session ? slotStatusLine(session.status) : null;
  const title = session ? (nodeLabel(graph, session.nodeId) ?? session.nodeId) : "Step transcript";

  return createPortal(
    <aside
      ref={panelRef}
      aria-labelledby={headingId}
      data-testid="step-drawer"
      // It closes on Escape, so page-wide Escape shortcuts (declining the open chat's
      // approval) leave the key alone while it is open.
      data-escape-owner=""
      className={DRAWER_PANEL_CLASS}
    >
      <header className="flex shrink-0 flex-col gap-1.5 border-border border-b px-4 py-3">
        <div className="flex items-center gap-2">
          <h2
            id={headingId}
            ref={headingRef}
            tabIndex={-1}
            className="min-w-0 flex-1 truncate text-ui font-medium text-foreground outline-none"
          >
            {title}
          </h2>
          {sessionId !== null && (
            <Link
              to={`/c/${encodeURIComponent(sessionId)}`}
              onClick={onFollow}
              componentId="workflows.run.step_drawer.open_in_chat"
              className="flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-sm text-muted-foreground hover:bg-muted hover:text-foreground"
            >
              <MessagesSquareIcon aria-hidden className="size-3.5" />
              Open in Chat
            </Link>
          )}
          <Button
            variant="ghost"
            size="icon"
            aria-label="Close"
            onClick={onClose}
            componentId="workflows.run.step_drawer.close"
          >
            <XIcon aria-hidden className="size-4" />
          </Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {session && <RosterChip profile={agentName(session)} harness={session.harness} />}
          {session?.pass != null && (
            <span className="text-sm text-muted-foreground">Pass {session.pass}</span>
          )}
          {/* Always in the tree, so a status that appears is announced. */}
          <p
            role="status"
            aria-live="polite"
            data-testid="step-drawer-status"
            className={cn("text-sm text-muted-foreground", status === null && "sr-only")}
          >
            {status}
          </p>
        </div>
      </header>
      {sessionId !== null ? (
        <StepTranscript key={sessionId} sessionId={sessionId} wasFollowed={wasFollowed} />
      ) : (
        <p className="m-auto px-6 text-center text-ui text-muted-foreground">{NOT_IN_RUN_TEXT}</p>
      )}
    </aside>,
    drawerRoot(),
  );
}

function StepTranscript({
  sessionId,
  wasFollowed,
}: {
  sessionId: string;
  /** Whether the person took this session to its Chat page in this tab. */
  wasFollowed: (sessionId: string) => boolean;
}) {
  // Read before the pane binds: an entry that is already live (a background chat, maybe
  // holding an unsent draft) is not the drawer's to release.
  const [createdHere] = useState(() => !conversationRegistry.has(sessionId));
  useEffect(() => {
    const unretain = conversationRegistry.retain(sessionId);
    return () => {
      unretain();
      if (!createdHere || wasFollowed(sessionId)) return;
      if (useChatStore.getState().conversationId === sessionId) return;
      releaseConversation(sessionId);
    };
  }, [sessionId, createdHere, wasFollowed]);
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* A transcript that cannot render leaves the drawer's Close and the run page working. */}
      <RenderErrorBoundary name="this step’s transcript">
        <SideChatPane childId={sessionId} fullSession readOnly />
      </RenderErrorBoundary>
    </div>
  );
}

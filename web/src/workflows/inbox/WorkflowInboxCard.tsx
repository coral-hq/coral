import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowRightIcon,
  BanIcon,
  BellIcon,
  CheckIcon,
  CircleCheckIcon,
  CirclePauseIcon,
  CircleXIcon,
  HandIcon,
  TimerIcon,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { ElicitationMessage } from "@/components/blocks/ElicitationMessage";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { InboxKindUi, InboxTileTone } from "@/lib/inboxKinds";
import { Link } from "@/lib/routing";
import { approve } from "@/lib/sessionsApi";
import type { WorkflowAlert, WorkflowAlertKind } from "../api/types";
import { runPath } from "../nav/coralPaths";
import { CardStatusLine } from "./CardStatusLine";
import { gateCardState, type GateSubmission } from "./cardState";
import { RunActions } from "./RunActions";
import { useOnline } from "./useOnline";
import { WORKFLOW_INBOX_QUERY_KEY } from "./useWorkflowInbox";
import { gateView, type WorkflowGateEntryData } from "./workflowEntries";

const PROMPT_PREVIEW_CHARS = 600;
const PROMPT_MAX_CHARS = 8_000;
const MAX_NOTE_CHARS = 2_000;

/** The gate's prompt as plain text; a long one is cut behind "Show more". */
function GatePrompt({ message }: { message: string }) {
  const [open, setOpen] = useState(false);
  const full = message.slice(0, PROMPT_MAX_CHARS);
  const long = full.length > PROMPT_PREVIEW_CHARS;
  return (
    <div className="flex flex-col items-start gap-1">
      <ElicitationMessage
        message={long && !open ? `${full.slice(0, PROMPT_PREVIEW_CHARS)}…` : full}
        className="text-ui break-words whitespace-pre-wrap"
      />
      {long && (
        <Button
          variant="link"
          size="xs"
          aria-expanded={open}
          onClick={() => setOpen(!open)}
          className="h-auto p-0"
        >
          {open ? "Show less" : "Show more"}
        </Button>
      )}
    </div>
  );
}

/** How the run page answers a gate: through the runs route, which needs no prompt id. */
export interface RunViewGate {
  /** Post the answer; a refusal rejects with its error. `note` is `null` when none was written. */
  answer: (outcome: string, note: string | null) => Promise<unknown>;
  /** Shown under the gate's prompt: what was checked before the work reached the gate. */
  evidence?: ReactNode;
}

export interface WorkflowGateCardProps {
  data: WorkflowGateEntryData;
  /** Epoch seconds. */
  at: number;
  viewerId: string | null;
  expanded: boolean;
  onToggle: () => void;
  ui: InboxKindUi;
  /** On the run page: answer through it, and leave out the Inbox's link to the run and notice. */
  runView?: RunViewGate;
}

/** One workflow gate: its context, and an answer posted to the anchor's prompt or the run. */
export function WorkflowGateCard({
  data,
  at,
  viewerId,
  expanded,
  onToggle,
  ui,
  runView,
}: WorkflowGateCardProps) {
  const view = gateView(data);
  const queryClient = useQueryClient();
  const online = useOnline();
  const noteId = useId();
  const statusRef = useRef<HTMLParagraphElement>(null);
  const [note, setNote] = useState("");
  const [submission, setSubmission] = useState<GateSubmission>({ status: "idle" });
  // The feed lists only the caller's own alerts; without one, the prompt names the owner.
  const owner = data.prompt?.runOwner ?? null;
  const isOwner = data.alert !== null || owner === null || owner === viewerId;
  const state = gateCardState({ isOwner, online, submission });
  const { elicitationId, sessionId } = view;
  const answerable = runView !== undefined || (elicitationId !== null && sessionId !== null);
  const showForm = state.showForm && answerable && view.outcomes.length > 0;
  const waitingHours =
    view.openedAt === null ? 0 : Math.floor((Date.now() / 1000 - view.openedAt) / 3600);

  useEffect(() => {
    if (submission.status === "failed") statusRef.current?.focus();
  }, [submission]);

  /** The answer's request: through the run page, else to the anchor's prompt; `null` without one. */
  const send = (decision: string, written: string | null): Promise<unknown> | null => {
    if (runView) return runView.answer(decision, written);
    if (elicitationId === null || sessionId === null) return null;
    const content: Record<string, unknown> = { decision };
    if (written !== null) content.note = written;
    return approve(sessionId, elicitationId, { action: "accept", content });
  };

  const submit = (decision: string) => {
    if (!state.canSubmit) return;
    const sent = send(decision, note.trim() === "" ? null : note);
    if (sent === null) return;
    setSubmission({ status: "submitting" });
    sent.then(
      () => {
        setSubmission({ status: "answered", label: decision });
        void queryClient.invalidateQueries({ queryKey: ["conversations"] });
        void queryClient.invalidateQueries({ queryKey: WORKFLOW_INBOX_QUERY_KEY });
      },
      (error: unknown) => setSubmission({ status: "failed", error }),
    );
  };

  return (
    <ui.InboxCard
      testId="inbox-workflow-gate"
      dataKind="workflow-gate"
      tile={<ui.KindTile icon={HandIcon} tone="yellow" />}
      kindLabel="Workflow gate"
      title={view.runTitle}
      preview={view.title}
      at={at}
      unread
      expanded={expanded}
      onToggle={onToggle}
    >
      <div className="flex flex-col gap-1">
        <p className="text-ui font-medium">{view.runTitle}</p>
        {view.stepLabel && <p className="text-sm text-muted-foreground">Step: {view.stepLabel}</p>}
        {waitingHours >= 1 && (
          <p className="text-sm text-muted-foreground">Waiting {waitingHours} h</p>
        )}
      </div>
      {view.message && <GatePrompt message={view.message} />}
      {runView?.evidence}
      {showForm && (
        <div className="flex flex-col gap-1.5">
          <label htmlFor={noteId} className="text-sm text-muted-foreground">
            Note
          </label>
          <Textarea
            id={noteId}
            value={note}
            maxLength={MAX_NOTE_CHARS}
            disabled={!state.canSubmit}
            onChange={(event) => setNote(event.target.value)}
            className="max-h-48 min-h-14 resize-none"
          />
        </div>
      )}
      <CardStatusLine
        ref={statusRef}
        message={state.message}
        failed={state.kind === "refused" || state.kind === "error"}
      />
      {!runView && (
        <p className="text-xs text-muted-foreground">Coral notifies you while the app is open.</p>
      )}
      <ui.InboxActions>
        {!runView && view.runId && (
          <Button asChild variant="outline" size="xs" className={ui.outlineAction}>
            <Link
              to={runPath(view.runId, { node: view.nodeId ?? undefined, panel: "gate" })}
              componentId="inbox.workflow_gate.open_run"
            >
              Open run <ArrowRightIcon className="size-3.5" />
            </Link>
          </Button>
        )}
        {showForm &&
          view.outcomes.map((outcome) => (
            <Button
              key={outcome}
              variant={outcome === "approve" ? "default" : "outline"}
              size="xs"
              className={outcome === "approve" ? ui.primaryAction : ui.outlineAction}
              disabled={!state.canSubmit}
              onClick={() => submit(outcome)}
              componentId={runView ? "workflows.run.gate.answer" : "inbox.workflow_gate.answer"}
            >
              {outcome}
            </Button>
          ))}
      </ui.InboxActions>
    </ui.InboxCard>
  );
}

const ALERT_LOOKS: Record<
  WorkflowAlertKind,
  { label: string; icon: LucideIcon; tone: InboxTileTone }
> = {
  gate: { label: "Workflow gate", icon: HandIcon, tone: "yellow" },
  question: { label: "Workflow question", icon: HandIcon, tone: "yellow" },
  pause: { label: "Run paused", icon: CirclePauseIcon, tone: "yellow" },
  watchdog: { label: "Decision waiting", icon: TimerIcon, tone: "yellow" },
  overdue: { label: "Run overdue", icon: TimerIcon, tone: "yellow" },
  reaction: { label: "Workflow alert", icon: BellIcon, tone: "gray" },
  run_completed: { label: "Run completed", icon: CircleCheckIcon, tone: "gray" },
  run_cancelled: { label: "Run cancelled", icon: BanIcon, tone: "gray" },
  run_failed: { label: "Run failed", icon: CircleXIcon, tone: "red" },
};

export interface WorkflowAlertCardProps {
  alert: WorkflowAlert;
  /** Epoch seconds. */
  at: number;
  expanded: boolean;
  onToggle: () => void;
  ui: InboxKindUi;
  onMarkRead: (alertId: string) => void;
}

/** A workflow alert that needs no answer: a pause, a waiting decision or a run's end. */
export function WorkflowAlertCard({
  alert,
  at,
  expanded,
  onToggle,
  ui,
  onMarkRead,
}: WorkflowAlertCardProps) {
  const look = ALERT_LOOKS[alert.kind];
  // A pause card's primary action is Resume, so Open run steps back there.
  const paused = alert.kind === "pause";
  const cardActions = (
    <>
      <Button
        asChild
        variant={paused ? "outline" : "default"}
        size="xs"
        className={paused ? ui.outlineAction : ui.primaryAction}
      >
        <Link
          to={runPath(alert.run_id, { node: alert.node_id ?? undefined })}
          componentId="inbox.workflow_alert.open_run"
        >
          Open run <ArrowRightIcon className="size-3.5" />
        </Link>
      </Button>
      {alert.actions.includes("mark_read") && (
        <Button
          variant="outline"
          size="xs"
          className={ui.outlineAction}
          onClick={() => onMarkRead(alert.alert_id)}
          componentId="inbox.workflow_alert.mark_read"
        >
          <CheckIcon className="size-3.5" /> Mark as read
        </Button>
      )}
    </>
  );
  return (
    <ui.InboxCard
      testId="inbox-workflow-alert"
      dataKind="workflow-alert"
      tile={<ui.KindTile icon={look.icon} tone={look.tone} />}
      kindLabel={look.label}
      title={alert.run_title}
      preview={alert.message}
      at={at}
      unread
      expanded={expanded}
      onToggle={onToggle}
    >
      <div className="flex flex-col gap-1">
        <p className="text-ui font-medium">{alert.title}</p>
        {alert.step_label && (
          <p className="text-sm text-muted-foreground">Step: {alert.step_label}</p>
        )}
      </div>
      <p className="text-ui break-words whitespace-pre-wrap text-muted-foreground">
        {alert.message}
      </p>
      {paused ? (
        <RunActions runId={alert.run_id} expanded={expanded} ui={ui}>
          {cardActions}
        </RunActions>
      ) : (
        <ui.InboxActions>{cardActions}</ui.InboxActions>
      )}
    </ui.InboxCard>
  );
}

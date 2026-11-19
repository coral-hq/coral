/** `GET /v1/coral/info` response (FND-02). */
export interface CoralInfo {
  enabled: boolean;
  version: string;
  sub_features: Record<string, boolean>;
}

/** Sub-feature keys the web shell gates on. */
export const CORAL_SUB_FEATURE = {
  profilesDesk: "profiles_desk",
} as const;

/** Kinds of a workflow alert (`GET /v1/coral/inbox`); question to reaction have no producer yet. */
export type WorkflowAlertKind =
  | "gate"
  | "question"
  | "pause"
  | "watchdog"
  | "overdue"
  | "reaction"
  | "run_completed"
  | "run_failed"
  | "run_cancelled";

/** What the owner can do with an alert; the card offers answer, open_run and mark_read. */
export type WorkflowAlertAction = "answer" | "open_run" | "mark_read" | "resume" | "cancel";

export type WorkflowAlertPriority = "normal" | "low";

/** One open alert of the caller: its row's fields merged with its payload. */
export interface WorkflowAlert {
  alert_id: string;
  run_id: string;
  run_title: string;
  kind: WorkflowAlertKind;
  priority: WorkflowAlertPriority;
  /** Epoch seconds. */
  created_at: number;
  title: string;
  message: string;
  step_label: string | null;
  node_id: string | null;
  actions: WorkflowAlertAction[];
  deep_link: string;
  approve_link: string | null;
  elicitation_id: string | null;
  /** The run anchor that holds the gate's prompt. */
  session_id: string | null;
  outcomes: string[];
  pause_reason: string | null;
}

/** One feed page; a page can be empty and still have a next cursor. */
export interface WorkflowInboxPage {
  data: WorkflowAlert[];
  next_cursor: string | null;
}

/** `params.coral` of a gate prompt on a run anchor. */
export interface GateElicitationCoral {
  kind: "gate";
  run_id: string;
  visit_id: string;
  node_id: string;
  visit_no: number;
  /** Epoch seconds. */
  opened_at: number;
  /** `null` is the single local user. */
  run_owner: string | null;
  run_title: string;
  outcomes: string[];
  deep_link: string;
}

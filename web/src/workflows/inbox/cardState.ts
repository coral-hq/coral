import { ApiError } from "@/lib/sessionsApi";
import { OFFLINE_TEXT } from "./useOnline";

// The gate card's state, as a pure function of who is looking, connectivity and
// the last answer sent. Refused answers carry their reason as "[reason] text".

/** A refused answer: the server's reason slug and its text. */
export interface GateRefusal {
  reason: string;
  text: string;
}

const REFUSAL = /^\[([a-z_]+)\] ([\s\S]*)$/;

/** The refusal in a failed answer, or `null` when it failed for another reason. */
export function refusalOf(error: unknown): GateRefusal | null {
  if (!(error instanceof ApiError)) return null;
  const match = REFUSAL.exec(error.message);
  if (match) return { reason: match[1]!, text: match[2]! };
  if (error.status === 403) return { reason: "not_permitted", text: error.message };
  return null;
}

export type GateSubmission =
  | { status: "idle" }
  | { status: "submitting" }
  | { status: "answered"; label: string }
  | { status: "failed"; error: unknown };

export interface GateCardInput {
  /** The viewer is the run's owner (who alone can answer). */
  isOwner: boolean;
  online: boolean;
  submission: GateSubmission;
}

export interface GateCardState {
  kind: "ready" | "readonly" | "offline" | "submitting" | "answered" | "refused" | "error";
  /** The refusal reason, for a refused answer. */
  reason: string | null;
  /** Status text for the card's live region. */
  message: string | null;
  showForm: boolean;
  canSubmit: boolean;
}

const OWNER_ONLY = "Only the run owner can answer this gate.";

/** Fixed text per reason; `null` shows the server's text. */
const REFUSAL_TEXT: Record<string, { text: string | null; keepForm: boolean }> = {
  not_permitted: { text: OWNER_ONLY, keepForm: false },
  no_caller: { text: OWNER_ONLY, keepForm: false },
  stale_visit: { text: "This gate was asked again. Answer the latest one.", keepForm: false },
  already_answered: { text: null, keepForm: false },
  no_longer_waiting: { text: "This gate is no longer waiting.", keepForm: false },
  run_paused: { text: "The run is paused. Resume it, then answer.", keepForm: true },
  invalid_answer: { text: null, keepForm: true },
  run_busy: { text: null, keepForm: true },
};

function state(
  kind: GateCardState["kind"],
  message: string | null,
  showForm: boolean,
  canSubmit = showForm,
  reason: string | null = null,
): GateCardState {
  return { kind, reason, message, showForm, canSubmit };
}

export function gateCardState({ isOwner, online, submission }: GateCardInput): GateCardState {
  if (!isOwner) return state("readonly", "Waiting for the run owner.", false);
  if (submission.status === "answered") {
    return state("answered", `Answered: ${submission.label}.`, false);
  }
  if (submission.status === "submitting") return state("submitting", "Sending…", true, false);
  const refusal = submission.status === "failed" ? refusalOf(submission.error) : null;
  const known = refusal ? REFUSAL_TEXT[refusal.reason] : undefined;
  const keepForm = known?.keepForm ?? true;
  const refused = (canSubmit: boolean) =>
    state("refused", known?.text ?? refusal!.text, keepForm, canSubmit, refusal!.reason);
  if (refusal && !keepForm) return refused(false);
  if (!online) return state("offline", OFFLINE_TEXT, true, false);
  if (refusal) return refused(true);
  if (submission.status === "failed") {
    return state("error", "Couldn’t send your answer. Try again.", true);
  }
  return state("ready", null, true);
}

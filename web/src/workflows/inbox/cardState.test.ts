import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/sessionsApi";
import { gateCardState, refusalOf, type GateCardInput, type GateSubmission } from "./cardState";

function refused(status: number, message: string): GateSubmission {
  return { status: "failed", error: new ApiError(message, status, null) };
}

describe("refusalOf", () => {
  it("reads the reason and text of a refused answer", () => {
    // WHY: ApiError carries only status, code and message, so the reason rides the message.
    expect(
      refusalOf(
        new ApiError(
          "[stale_visit] This gate was asked again; answer the latest one.",
          409,
          "conflict",
        ),
      ),
    ).toEqual({ reason: "stale_visit", text: "This gate was asked again; answer the latest one." });
  });

  it("treats a 403 without a reason as not permitted", () => {
    // WHY: a proxy or route refusal before the handler still means "not yours to answer".
    expect(refusalOf(new ApiError("Forbidden", 403, null))).toEqual({
      reason: "not_permitted",
      text: "Forbidden",
    });
  });

  it("finds no refusal in other failures", () => {
    // WHY: only a reasoned refusal gets refusal text; anything else is a send error.
    expect(refusalOf(new ApiError("Conflict", 409, null))).toBeNull();
    expect(refusalOf(new ApiError("500 Internal Server Error", 500, null))).toBeNull();
    expect(refusalOf(new Error("[stale_visit] not from the server"))).toBeNull();
    expect(refusalOf(new TypeError("Failed to fetch"))).toBeNull();
  });
});

describe("gateCardState", () => {
  const owner: GateCardInput = { isOwner: true, online: true, submission: { status: "idle" } };

  it.each<[string, GateCardInput, string, string | null, boolean, boolean]>([
    ["ready", owner, "ready", null, true, true],
    [
      "readonly",
      { ...owner, isOwner: false },
      "readonly",
      "Waiting for the run owner.",
      false,
      false,
    ],
    [
      "readonly while offline",
      { ...owner, isOwner: false, online: false },
      "readonly",
      "Waiting for the run owner.",
      false,
      false,
    ],
    ["offline", { ...owner, online: false }, "offline", "You’re offline.", true, false],
    [
      "submitting",
      { ...owner, submission: { status: "submitting" } },
      "submitting",
      "Sending…",
      true,
      false,
    ],
    [
      "answered",
      { ...owner, submission: { status: "answered", label: "approve" } },
      "answered",
      "Answered: approve.",
      false,
      false,
    ],
    [
      "not_permitted",
      {
        ...owner,
        submission: refused(403, "[not_permitted] Only the run owner can answer this gate."),
      },
      "refused",
      "Only the run owner can answer this gate.",
      false,
      false,
    ],
    [
      "no_caller",
      { ...owner, submission: refused(403, "[no_caller] No caller.") },
      "refused",
      "Only the run owner can answer this gate.",
      false,
      false,
    ],
    [
      "a bare 403",
      { ...owner, submission: refused(403, "Forbidden") },
      "refused",
      "Only the run owner can answer this gate.",
      false,
      false,
    ],
    [
      "stale_visit",
      {
        ...owner,
        submission: refused(409, "[stale_visit] This gate was asked again; answer the latest one."),
      },
      "refused",
      "This gate was asked again. Answer the latest one.",
      false,
      false,
    ],
    [
      "already_answered",
      { ...owner, submission: refused(409, "[already_answered] Already answered: reject.") },
      "refused",
      "Already answered: reject.",
      false,
      false,
    ],
    [
      "no_longer_waiting",
      { ...owner, submission: refused(409, "[no_longer_waiting] This gate is no longer waiting.") },
      "refused",
      "This gate is no longer waiting.",
      false,
      false,
    ],
    [
      "run_paused",
      {
        ...owner,
        submission: refused(409, "[run_paused] The run is paused; resume it, then answer."),
      },
      "refused",
      "The run is paused. Resume it, then answer.",
      true,
      true,
    ],
    [
      "invalid_answer",
      { ...owner, submission: refused(409, "[invalid_answer] Choose one of: approve, reject.") },
      "refused",
      "Choose one of: approve, reject.",
      true,
      true,
    ],
    [
      "run_busy",
      { ...owner, submission: refused(409, "[run_busy] The run is busy; try again.") },
      "refused",
      "The run is busy; try again.",
      true,
      true,
    ],
    [
      "a reason this client does not know",
      { ...owner, submission: refused(409, "[too_many_answers] Too many answers; try again.") },
      "refused",
      "Too many answers; try again.",
      true,
      true,
    ],
    [
      "a network failure",
      { ...owner, submission: { status: "failed", error: new TypeError("Failed to fetch") } },
      "error",
      "Couldn’t send your answer. Try again.",
      true,
      true,
    ],
    [
      "a server error",
      { ...owner, submission: refused(500, "500 Internal Server Error") },
      "error",
      "Couldn’t send your answer. Try again.",
      true,
      true,
    ],
    [
      "offline after a refusal that keeps the form",
      {
        ...owner,
        online: false,
        submission: refused(409, "[run_busy] The run is busy; try again."),
      },
      "offline",
      "You’re offline.",
      true,
      false,
    ],
    [
      "offline after a refusal that hides the form",
      { ...owner, online: false, submission: refused(409, "[no_longer_waiting] Gone.") },
      "refused",
      "This gate is no longer waiting.",
      false,
      false,
    ],
  ])("maps %s", (_name, input, kind, message, showForm, canSubmit) => {
    // WHY: every state row of the card's table shows its exact text and form.
    expect(gateCardState(input)).toMatchObject({ kind, message, showForm, canSubmit });
  });

  it("keeps the refusal reason for the card", () => {
    // WHY: the card moves focus to the status after a refusal, keyed on the reason.
    expect(gateCardState({ ...owner, submission: refused(409, "[stale_visit] x") }).reason).toBe(
      "stale_visit",
    );
    expect(gateCardState(owner).reason).toBeNull();
  });
});

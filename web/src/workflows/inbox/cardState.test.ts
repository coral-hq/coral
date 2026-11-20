import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/sessionsApi";
import { coralError, CoralRequestError } from "../api/runsApi";
import { gateCardState, refusalOf, type GateCardInput, type GateSubmission } from "./cardState";

function refused(status: number, message: string): GateSubmission {
  return { status: "failed", error: new ApiError(message, status, null) };
}

/** A runs-route refusal, as the run view's gate card receives it. */
function coralRefusal(
  status: number,
  code: string,
  message: string,
  details: Record<string, unknown> | null = null,
): CoralRequestError {
  return new CoralRequestError(message, status, code, details);
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

  it("reads a runs-route refusal's reason from its details", () => {
    // WHY: the runs route keeps the reason in details.reason, not in the message.
    expect(
      refusalOf(
        coralRefusal(409, "illegal_transition", "The run is paused; resume it, then answer.", {
          reason: "run_paused",
        }),
      ),
    ).toEqual({ reason: "run_paused", text: "The run is paused; resume it, then answer." });
    expect(
      refusalOf(coralRefusal(503, "server_busy", "The run is busy.", { reason: "run_busy" })),
    ).toEqual({ reason: "run_busy", text: "The run is busy." });
  });

  it("reads a runs-route stale visit and 404 by code and status", () => {
    // WHY: those two refusals carry no details.reason; a visit the run lacks is the run 404.
    expect(refusalOf(coralRefusal(409, "stale_visit", "Asked again."))).toEqual({
      reason: "stale_visit",
      text: "Asked again.",
    });
    expect(refusalOf(coralRefusal(404, "not_found", "Run not found."))).toEqual({
      reason: "no_longer_waiting",
      text: "Run not found.",
    });
  });

  it("ignores a details reason that is not a string", () => {
    // WHY: details come from the wire; only a string names a reason.
    expect(
      refusalOf(coralRefusal(409, "illegal_transition", "Conflict", { reason: 3 })),
    ).toBeNull();
  });

  it("keeps reading an anchor-route 404 as no refusal", () => {
    // WHY: the Inbox's prompt route answers 404 for other things; its card stays as it was.
    expect(refusalOf(new ApiError("Not found.", 404, "not_found"))).toBeNull();
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

  it.each<[string, CoralRequestError, string, boolean]>([
    [
      "a paused run",
      coralRefusal(409, "illegal_transition", "The run is paused; resume it, then answer.", {
        reason: "run_paused",
      }),
      "The run is paused. Resume it, then answer.",
      true,
    ],
    [
      "a stale visit",
      coralRefusal(409, "stale_visit", "This gate was asked again; answer the latest one."),
      "This gate was asked again. Answer the latest one.",
      false,
    ],
    [
      "a visit the run no longer has",
      coralRefusal(404, "not_found", "Run not found."),
      "This gate is no longer waiting.",
      false,
    ],
    [
      "an answer already given",
      coralRefusal(409, "illegal_transition", "Already answered: reject.", {
        reason: "already_answered",
      }),
      "Already answered: reject.",
      false,
    ],
    [
      "an outcome the gate lacks",
      coralRefusal(422, "validation_failed", "Choose one of: approve, reject.", {
        reason: "invalid_answer",
      }),
      "Choose one of: approve, reject.",
      true,
    ],
    [
      "a busy run",
      coralRefusal(503, "server_busy", "The run is busy; try again.", { reason: "run_busy" }),
      "The run is busy; try again.",
      true,
    ],
  ])("maps a runs-route refusal for %s", (_name, error, message, showForm) => {
    // WHY: the run view's gate card shows the Inbox card's texts for the runs route's refusals.
    expect(gateCardState({ ...owner, submission: { status: "failed", error } })).toMatchObject({
      kind: "refused",
      message,
      showForm,
      canSubmit: showForm,
    });
  });

  it.each(["constructor", "toString", "hasOwnProperty", "__proto__"])(
    "reads the reason %j as one it does not know, never as a prototype member",
    (reason) => {
      // WHY: a runs-route reason comes off the wire; only the table's own entries are copy.
      const error = coralRefusal(409, "illegal_transition", "Something new.", { reason });
      expect(gateCardState({ ...owner, submission: { status: "failed", error } })).toMatchObject({
        kind: "refused",
        reason,
        message: "Something new.",
        showForm: true,
        canSubmit: true,
      });
    },
  );

  it("keeps the refusal reason for the card", () => {
    // WHY: the card moves focus to the status after a refusal, keyed on the reason.
    expect(gateCardState({ ...owner, submission: refused(409, "[stale_visit] x") }).reason).toBe(
      "stale_visit",
    );
    expect(gateCardState(owner).reason).toBeNull();
  });
});

describe("a runs-route gate answer's refusal, as the server sends it", () => {
  const OWNER: GateCardInput = { isOwner: true, online: true, submission: { status: "idle" } };

  /** The wire body the runs route answers a refused gate answer with. */
  const wire = (status: number, body: string, headers: Record<string, string> = {}) =>
    new Response(body, { status, headers });
  const refusal = (code: string, message: string, details: unknown) =>
    JSON.stringify({ error: { code, message, details } });

  it.each<[string, Response, Partial<ReturnType<typeof gateCardState>>]>([
    [
      "a visit the run does not have (the run 404)",
      wire(404, refusal("not_found", "Run not found.", null)),
      {
        kind: "refused",
        reason: "no_longer_waiting",
        message: "This gate is no longer waiting.",
        showForm: false,
      },
    ],
    [
      "a stale visit",
      wire(
        409,
        refusal("stale_visit", "This gate was asked again; answer the latest one.", {
          reason: "stale_visit",
        }),
      ),
      {
        kind: "refused",
        reason: "stale_visit",
        message: "This gate was asked again. Answer the latest one.",
        showForm: false,
      },
    ],
    [
      "an answer already given",
      wire(
        409,
        refusal("illegal_transition", "This gate was already answered.", {
          reason: "already_answered",
        }),
      ),
      {
        kind: "refused",
        reason: "already_answered",
        message: "This gate was already answered.",
        showForm: false,
      },
    ],
    [
      "a gate no longer waiting",
      wire(
        409,
        refusal("illegal_transition", "This gate is no longer waiting.", {
          reason: "no_longer_waiting",
        }),
      ),
      {
        kind: "refused",
        reason: "no_longer_waiting",
        message: "This gate is no longer waiting.",
        showForm: false,
      },
    ],
    [
      "a paused run",
      wire(
        409,
        refusal("illegal_transition", "The run is paused; resume it, then answer.", {
          reason: "run_paused",
        }),
      ),
      {
        kind: "refused",
        reason: "run_paused",
        message: "The run is paused. Resume it, then answer.",
        showForm: true,
        canSubmit: true,
      },
    ],
    [
      "a note that is too long",
      wire(
        422,
        refusal("validation_failed", "The note must be text of at most 4,000 characters.", {
          reason: "invalid_answer",
        }),
      ),
      {
        kind: "refused",
        reason: "invalid_answer",
        message: "The note must be text of at most 4,000 characters.",
        showForm: true,
        canSubmit: true,
      },
    ],
    [
      "a busy run",
      wire(
        503,
        refusal("server_busy", "Too many gate answers at once; try again.", { reason: "run_busy" }),
        { "Retry-After": "1" },
      ),
      {
        kind: "refused",
        reason: "run_busy",
        message: "Too many gate answers at once; try again.",
        showForm: true,
        canSubmit: true,
      },
    ],
    [
      "a busy server, with no reason",
      wire(503, refusal("server_busy", "The server is busy; try again.", null), {
        "Retry-After": "1",
      }),
      {
        kind: "error",
        reason: null,
        message: "Couldn’t send your answer. Try again.",
        showForm: true,
      },
    ],
    [
      "a malformed request",
      wire(
        422,
        refusal("validation_failed", "The request is invalid.", {
          errors: [{ loc: ["body", "outcome"] }],
        }),
      ),
      { kind: "error", reason: null, showForm: true },
    ],
    [
      "a reason hidden under __proto__",
      wire(
        409,
        '{"error":{"code":"illegal_transition","message":"No.","details":{"__proto__":{"reason":"run_paused"}}}}',
      ),
      { kind: "error", reason: null, showForm: true },
    ],
    [
      "a reason this client does not know",
      wire(409, refusal("illegal_transition", "The gate is locked.", { reason: "gate_locked" })),
      {
        kind: "refused",
        reason: "gate_locked",
        message: "The gate is locked.",
        showForm: true,
        canSubmit: true,
      },
    ],
    [
      "a proxy's HTML 404",
      wire(404, "<html>Not Found</html>"),
      { kind: "error", reason: null, showForm: true },
    ],
  ])("shows %s with the Inbox card's text", async (_name, response, expected) => {
    // WHY: the run view's gate card reads the reason only from details.reason, the code or the run 404.
    const error = await coralError(response);
    expect(gateCardState({ ...OWNER, submission: { status: "failed", error } })).toMatchObject(
      expected,
    );
  });
});

import { describe, expect, it } from "vitest";
import type { PauseCause, RunHeader } from "../api/generated/coralApi";
import { CONTRACT_GRAPH, CONTRACT_PAUSE_MESSAGES } from "../fixtures/runViewContract";
import {
  LOAD_FAILED_TEXT,
  PAUSE_MESSAGES,
  pauseCopy,
  slotNodeId,
  UNKNOWN_PAUSE_TEXT,
  type PauseReasonName,
} from "./pauseCopy";

/** Every pause reason the generated union names; `tsc` fails here when the server adds one. */
const REASONS = [
  "user",
  "failure_path",
  "infra",
  "plan_limit",
  "auth",
  "budget",
  "rejected_calls",
  "liveness",
  "drift",
  "authority_revoked",
  "engine_upgrade",
  "gate",
  "merge_conflict",
] as const satisfies readonly PauseReasonName[];
const COVERED: [Exclude<NonNullable<RunHeader["pause_reason"]>, (typeof REASONS)[number]>] extends [
  never,
]
  ? true
  : false = true;

const SERVER = CONTRACT_PAUSE_MESSAGES.by_reason;

function cause(reason: PauseCause["reason"], detail: string, subject = ""): PauseCause {
  return { reason, detail, subject };
}

describe("pauseCopy", () => {
  it("covers every reason of the generated union and of the server's alert copy", () => {
    // WHY: a reason the server pauses for must never reach the banner without copy. The union
    // check is `tsc` (COVERED's type is `false` once the union gains a reason); at run time
    // only the fixture's reason set is compared.
    expect(COVERED).toBe(true);
    expect(new Set(Object.keys(SERVER))).toEqual(
      new Set(REASONS.filter((reason) => reason !== "user")),
    );
  });

  it("keeps the server's pause alert copy as its fallback bodies", () => {
    // WHY: the banner and the Inbox's pause alert say the same thing when nothing is more specific.
    expect(PAUSE_MESSAGES).toEqual(SERVER);
    expect(UNKNOWN_PAUSE_TEXT).toBe(CONTRACT_PAUSE_MESSAGES.unknown);
  });

  it.each<[PauseReasonName, string, string]>([
    ["user", "by you", UNKNOWN_PAUSE_TEXT],
    ["failure_path", "step failed", SERVER.failure_path],
    ["infra", "infrastructure", SERVER.infra],
    ["plan_limit", "plan limit", `${SERVER.plan_limit} Coral retries periodically.`],
    ["auth", "sign-in needed", SERVER.auth],
    ["budget", "activation cap", SERVER.budget],
    ["rejected_calls", "refused calls", SERVER.rejected_calls],
    ["liveness", "step waiting", SERVER.liveness],
    ["drift", "session changed", SERVER.drift],
    ["authority_revoked", "account access revoked", SERVER.authority_revoked],
    ["engine_upgrade", "Coral upgraded", "Coral was upgraded; this run cannot continue."],
    ["gate", "gate", SERVER.gate],
    ["merge_conflict", "merge conflict", SERVER.merge_conflict],
  ])("labels %s and gives its body without a cause", (reason, label, body) => {
    // WHY: every reason's pill and banner have fixed copy, whatever the server's detail.
    expect(pauseCopy(reason, null, CONTRACT_GRAPH)).toEqual({
      label,
      title: `Paused: ${label}`,
      body,
    });
  });

  it.each<[string, string | null]>([
    ["a reason it does not know", "solar_flare"],
    ["no reason", null],
  ])("says only that the run paused for %s", (_name, reason) => {
    // WHY: a newer server's reason still gets an honest banner.
    expect(pauseCopy(reason, null, CONTRACT_GRAPH)).toEqual({
      label: null,
      title: "Paused",
      body: UNKNOWN_PAUSE_TEXT,
    });
  });

  it.each<[string, PauseCause, string]>([
    [
      "missing evidence",
      cause("failure_path", "attempts_exhausted", "pytest -q, ruff check src"),
      "Missing evidence: pytest -q, ruff check src.",
    ],
    [
      "missing evidence it cannot name",
      cause("failure_path", "attempts_exhausted"),
      SERVER.failure_path,
    ],
    ["a run that cannot load", cause("failure_path", "engine.load_failed"), LOAD_FAILED_TEXT],
    ["another failure", cause("failure_path", "blocked", "implement||:0"), SERVER.failure_path],
    [
      "a join waiting on a step that cannot run",
      cause(
        "liveness",
        "approve_change is waiting for implement, which can no longer run.",
        "implement",
      ),
      "Approve change is waiting for Implement, which can no longer run.",
    ],
    [
      "a join on unnamed nodes",
      cause("liveness", "end is waiting for start, which can no longer run.", "start"),
      "end is waiting for start, which can no longer run.",
    ],
    [
      "a join on a node the graph lacks",
      cause("liveness", "approve_change is waiting for deploy, which can no longer run.", "deploy"),
      SERVER.liveness,
    ],
    ["a liveness detail of another form", cause("liveness", "stuck"), SERVER.liveness],
    [
      "an archived anchor",
      cause("drift", "anchor_archived"),
      "The run’s session was archived. Unarchive it to continue, or cancel.",
    ],
    [
      "a deleted anchor",
      cause("drift", "anchor_deleted"),
      "The run’s session was deleted. The run can only be cancelled.",
    ],
    [
      "a step someone typed into",
      cause("drift", "pending_input", "implement||a4:2:0"),
      "Someone typed into Implement’s session while Coral was finishing it.",
    ],
    [
      "a step that kept working",
      cause("drift", "post_close", "implement||a4:1:0"),
      "Implement’s session kept working after its step closed.",
    ],
    ["a typed-into slot it cannot read", cause("drift", "pending_input", "x"), SERVER.drift],
    [
      "a typed-into slot of a node the graph lacks",
      cause("drift", "pending_input", "deploy||:0"),
      SERVER.drift,
    ],
    ["an archived step session", cause("drift", "session_archived", "s1"), SERVER.drift],
    [
      "a plan limit with a detail",
      cause("plan_limit", "plan_limit.weekly"),
      `${SERVER.plan_limit} Coral retries periodically.`,
    ],
    [
      "an engine upgrade",
      cause("engine_upgrade", "engine.version"),
      "Coral was upgraded; this run cannot continue.",
    ],
    [
      "a refused call",
      cause("rejected_calls", "nudge_limit", "implement||:0"),
      SERVER.rejected_calls,
    ],
  ])("says what %s means", (_name, pauseCause, body) => {
    // WHY: the detail codes the engine records get the roadmap's specific copy.
    expect(pauseCopy(pauseCause.reason, pauseCause, CONTRACT_GRAPH).body).toBe(body);
  });

  it("falls back to the reason's copy for named steps until the graph loads", () => {
    // WHY: names come only from the graph; a bare id from free text is not shown as a name.
    expect(
      pauseCopy(
        "liveness",
        cause("liveness", "approve_change is waiting for implement, which can no longer run."),
        null,
      ).body,
    ).toBe(SERVER.liveness);
    expect(pauseCopy("drift", cause("drift", "post_close", "implement||a4:1:0"), null).body).toBe(
      SERVER.drift,
    );
  });

  it("titles the run's reason and describes its cause", () => {
    // WHY: the banner names the row's reason, then explains the first cause in its own terms.
    expect(pauseCopy("drift", cause("failure_path", "engine.load_failed"), null)).toEqual({
      label: "session changed",
      title: "Paused: session changed",
      body: LOAD_FAILED_TEXT,
    });
    expect(pauseCopy(null, cause("budget", "activation_cap", "implement"), null)).toEqual({
      label: "activation cap",
      title: "Paused: activation cap",
      body: SERVER.budget,
    });
  });

  it("explains a cause it cannot name by the run's own reason", () => {
    // WHY: the copy order is specific, then the reason's server copy, then "The run paused.".
    const newer = { reason: "solar_flare", detail: "anchor_archived", subject: "" };
    expect(pauseCopy("failure_path", newer, CONTRACT_GRAPH)).toEqual({
      label: "step failed",
      title: "Paused: step failed",
      body: SERVER.failure_path,
    });
    expect(pauseCopy("plan_limit", newer, CONTRACT_GRAPH).body).toBe(
      `${SERVER.plan_limit} Coral retries periodically.`,
    );
    expect(pauseCopy(null, newer, CONTRACT_GRAPH)).toEqual({
      label: null,
      title: "Paused",
      body: UNKNOWN_PAUSE_TEXT,
    });
  });

  it("names a step with a blank name by its id", () => {
    // WHY: authoring allows an empty name, and the copy must never name a step as nothing.
    const graph = {
      nodes: [
        { id: "a", name: "" },
        { id: "b", name: "  " },
      ],
    };
    expect(
      pauseCopy(
        "liveness",
        cause("liveness", "a is waiting for b, which can no longer run.", "b"),
        graph,
      ).body,
    ).toBe("a is waiting for b, which can no longer run.");
    expect(pauseCopy("drift", cause("drift", "post_close", "a||:0"), graph).body).toBe(
      "a’s session kept working after its step closed.",
    );
  });

  it("keeps its client-only copy in curly apostrophes and the server's copy byte for byte", () => {
    // WHY: the web's own copy uses ’, while the alert copy must equal the server's exactly.
    expect(LOAD_FAILED_TEXT).toBe("This run can’t be loaded. You can still cancel it.");
    expect(PAUSE_MESSAGES.plan_limit).toBe("A step reached its plan's usage limit.");
  });
});

describe("slotNodeId", () => {
  it.each<[string, string | null]>([
    ["implement||a4:2:0", "implement"],
    ["review|items/0|:1", "review"],
    ["implement||a4:2", "implement"],
    ["implement:0", null],
    ["", null],
    [":0", null],
    ["|x|:0", null],
  ])("reads the node of slot %j", (slotId, nodeId) => {
    // WHY: a slot is `<activation>:<index>` and an activation `<node>|<item>|<iteration>`.
    expect(slotNodeId(slotId)).toBe(nodeId);
  });
});

describe("pauseCopy for odd reasons and details", () => {
  // Names an object lookup would find on its prototype, and an empty reason.
  it.each(["", "constructor", "__proto__", "toString", "hasOwnProperty"])(
    "gives the reason %j the unknown copy, as the run's reason or its cause's",
    (reason) => {
      // WHY: a lookup by a wire string must never read Object.prototype as copy.
      const unknown = { label: null, title: "Paused", body: UNKNOWN_PAUSE_TEXT };
      expect(pauseCopy(reason, null, CONTRACT_GRAPH)).toEqual(unknown);
      expect(
        pauseCopy(null, { reason, detail: "anchor_archived", subject: "" }, CONTRACT_GRAPH),
      ).toEqual(unknown);
    },
  );

  // Each detail code the engine records, with a subject the graph can name.
  const DETAILS: [string, string][] = [
    ["attempts_exhausted", "pytest -q"],
    ["engine.load_failed", ""],
    ["approve_change is waiting for implement, which can no longer run.", "implement"],
    ["anchor_archived", ""],
    ["anchor_deleted", ""],
    ["pending_input", "implement||a4:2:0"],
    ["post_close", "implement||a4:1:0"],
  ];
  const OWNER: Record<string, PauseReasonName> = {
    attempts_exhausted: "failure_path",
    "engine.load_failed": "failure_path",
    anchor_archived: "drift",
    anchor_deleted: "drift",
    pending_input: "drift",
    post_close: "drift",
  };

  it("gives every reason its own body for a detail code another reason owns", () => {
    // WHY: a detail code is specific only under its own reason; elsewhere the reason's copy stands.
    for (const reason of REASONS) {
      const plain = pauseCopy(reason, null, CONTRACT_GRAPH).body;
      for (const [detail, subject] of DETAILS) {
        const owner = OWNER[detail] ?? "liveness";
        if (owner === reason) continue;
        expect(
          pauseCopy(reason, { reason, detail, subject }, CONTRACT_GRAPH).body,
          `${reason} / ${detail}`,
        ).toBe(plain);
      }
    }
  });
});

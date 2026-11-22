import { describe, expect, it } from "vitest";
import type { PauseCause, RunHeader } from "../api/generated/coralApi";
import { CONTRACT_GRAPH, CONTRACT_PAUSE_MESSAGES } from "../fixtures/runViewContract";
import {
  isolated,
  LOAD_FAILED_TEXT,
  PAUSE_MESSAGES,
  pauseCopy,
  stallSentences,
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
      `Missing evidence: ${isolated("pytest -q, ruff check src")}.`,
    ],
    [
      "missing evidence it cannot name",
      cause("failure_path", "attempts_exhausted"),
      SERVER.failure_path,
    ],
    ["a run that cannot load", cause("failure_path", "engine.load_failed"), LOAD_FAILED_TEXT],
    [
      "another failure",
      cause("failure_path", "agent.failed", "implement||:0"),
      SERVER.failure_path,
    ],
    [
      "a join waiting on a step that cannot run",
      cause(
        "liveness",
        "approve_change is waiting for implement, which can no longer run.",
        "implement",
      ),
      `${isolated("Approve change")} is waiting for ${isolated("Implement")}, which can no longer run.`,
    ],
    [
      "a join on unnamed nodes",
      cause("liveness", "end is waiting for start, which can no longer run.", "start"),
      `${isolated("end")} is waiting for ${isolated("start")}, which can no longer run.`,
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
      `Someone typed into ${isolated("Implement")}’s session while Coral was finishing it.`,
    ],
    [
      "a step that kept working",
      cause("drift", "post_close", "implement||a4:1:0"),
      `${isolated("Implement")}’s session kept working after its step closed.`,
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

  const STEP = isolated("Implement");
  const SLOT = "implement||a4:2:0";
  // Each step cause's body, for the detail the engine records, on a slot the graph names.
  const STEP_CAUSE_COPY: [string, PauseCause, string][] = [
    [
      "a step held while its machine is offline",
      cause("infra", "infra.host_offline", SLOT),
      `Your machine went offline. Coral will continue ${STEP} when it’s back.`,
    ],
    [
      "a step restarting after a Retry",
      cause("infra", "recovery.restarting", SLOT),
      `Coral is restarting ${STEP} from its last handoff.`,
    ],
    [
      "a step that used its runner wakes",
      cause("infra", "infra.runner_lost", SLOT),
      `${STEP} keeps losing its runner. Resume tries again; Retry restarts it from its last handoff.`,
    ],
    [
      "a step whose runner is alive but unreachable",
      cause("infra", "recovery.runner_alive", SLOT),
      `${STEP}’s runner is running but can’t reach Coral. Resume tries again.`,
    ],
    ...["dispatch.stop_unconfirmed", "session.host_offline", "workspace.backend_unavailable"].map(
      (code): [string, PauseCause, string] => [
        `a restart that could not reach the machine (${code})`,
        cause("failure_path", `restart:${code}`, SLOT),
        `Your machine went offline before ${STEP} could restart. Retry when it’s back.`,
      ],
    ),
    [
      "a restart refused because the branch moved",
      cause("failure_path", "restart:workspace.head_moved", SLOT),
      `The run’s branch moved outside Coral, so ${STEP} was not restarted. Reset the branch to ` +
        "the commit of its last handoff, then retry; or cancel the run.",
    ],
    ...["workspace.tree_changed", "session.not_bound", ""].map(
      (code): [string, PauseCause, string] => [
        `another failed restart (${JSON.stringify(code)})`,
        cause("failure_path", `restart:${code}`, SLOT),
        `Coral couldn’t restart ${STEP}. Retry tries again.`,
      ],
    ),
    [
      "a step whose machine cannot run Coral steps",
      cause("failure_path", "session.host_unsupported", SLOT),
      `${STEP}’s machine can’t run Coral steps. Update Coral there, then retry.`,
    ],
    [
      "a step that reported it is blocked",
      cause("failure_path", "blocked", SLOT),
      `${STEP} reported that it is blocked. Retry restarts it from its last handoff.`,
    ],
    [
      "missing evidence named in the detail",
      cause("failure_path", "attempts_exhausted:pytest -q, ruff check src", SLOT),
      `Missing evidence: ${isolated("pytest -q, ruff check src")}.`,
    ],
    [
      "missing evidence the detail cannot name",
      cause("failure_path", "attempts_exhausted:", SLOT),
      SERVER.failure_path,
    ],
    // Specific bodies for causes that would otherwise keep the reason's copy.
    [
      "a step session someone closed",
      cause("failure_path", "session.closed", SLOT),
      `${STEP}’s session was closed, so it can’t go on. Retry starts it again from its last handoff.`,
    ],
    [
      "a runner status the host cannot give",
      cause("infra", "session.runner_status_unknown", SLOT),
      `Coral couldn’t check ${STEP}’s runner on your machine. Resume tries again.`,
    ],
    // Causes with no body of their own keep the reason's copy.
    ...["session.not_bound", "session.host_not_permitted", "session.deleted"].map(
      (code): [string, PauseCause, string] => [
        `a wake refused with ${code}`,
        cause("failure_path", code, SLOT),
        SERVER.failure_path,
      ],
    ),
    ["an exhausted wake retry", cause("infra", "run.contended", SLOT), SERVER.infra],
    ["a turn that kept failing", cause("infra", "infra.transient", SLOT), SERVER.infra],
  ];

  it.each(STEP_CAUSE_COPY)("says what %s means", (_name, pauseCause, body) => {
    // WHY: a held, restarting or failed step says what happens next and what the owner can do.
    expect(pauseCopy(pauseCause.reason, pauseCause, CONTRACT_GRAPH)).toEqual({
      ...pauseCopy(pauseCause.reason, null, CONTRACT_GRAPH),
      body,
    });
  });

  it.each<[string, PauseCause, string]>([
    [
      "a held step",
      cause("infra", "infra.host_offline", "deploy||:0"),
      "Your machine went offline. Coral will continue a step when it’s back.",
    ],
    [
      "a restarting step",
      cause("infra", "recovery.restarting", "x"),
      "Coral is restarting a step from its last handoff.",
    ],
    [
      "a step losing its runner",
      cause("infra", "infra.runner_lost", ""),
      "A step keeps losing its runner. Resume tries again; Retry restarts it from its last handoff.",
    ],
    [
      "an unreachable runner",
      cause("infra", "recovery.runner_alive", "deploy||:0"),
      "A step’s runner is running but can’t reach Coral. Resume tries again.",
    ],
    [
      "a moved branch",
      cause("failure_path", "restart:workspace.head_moved", "deploy||:0"),
      "The run’s branch moved outside Coral, so a step was not restarted. Reset the branch to " +
        "the commit of its last handoff, then retry; or cancel the run.",
    ],
    [
      "a failed restart",
      cause("failure_path", "restart:workspace.tree_changed", "deploy||:0"),
      "Coral couldn’t restart a step. Retry tries again.",
    ],
    [
      "an unsupported machine",
      cause("failure_path", "session.host_unsupported", "deploy||:0"),
      "A step’s machine can’t run Coral steps. Update Coral there, then retry.",
    ],
    [
      "a blocked step",
      cause("failure_path", "blocked", "deploy||:0"),
      "A step reported that it is blocked. Retry restarts it from its last handoff.",
    ],
    [
      "a closed step session",
      cause("failure_path", "session.closed", "deploy||:0"),
      "A step’s session was closed, so it can’t go on. Retry starts it again from its last handoff.",
    ],
    [
      "an unknown runner status",
      cause("infra", "session.runner_status_unknown", "deploy||:0"),
      "Coral couldn’t check a step’s runner on your machine. Resume tries again.",
    ],
    [
      "a restart on an offline machine",
      cause("failure_path", "restart:session.host_offline", "deploy||:0"),
      "Your machine went offline before a step could restart. Retry when it’s back.",
    ],
  ])("speaks of %s as a step when the graph cannot name it", (_name, pauseCause, body) => {
    // WHY: names come only from the graph; a slot id or a missing node is never shown.
    expect(pauseCopy(pauseCause.reason, pauseCause, CONTRACT_GRAPH).body).toBe(body);
  });

  it("names a step cause's step only once the graph loads", () => {
    // WHY: before the graph arrives the banner still explains the cause, without a name.
    expect(pauseCopy("infra", cause("infra", "recovery.restarting", SLOT), null).body).toBe(
      "Coral is restarting a step from its last handoff.",
    );
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
    ).toBe(`${isolated("a")} is waiting for ${isolated("b")}, which can no longer run.`);
    expect(pauseCopy("drift", cause("drift", "post_close", "a||:0"), graph).body).toBe(
      `${isolated("a")}’s session kept working after its step closed.`,
    );
  });

  it("isolates a step name or command written into its copy", () => {
    // WHY: names and commands come from the workflow's YAML; a right-to-left override in
    // one must not reorder the fixed words after it.
    const graph = { nodes: [{ id: "a", name: "Impl\u202eement" }] };
    expect(isolated("Impl\u202eement")).toBe("\u2068Impl\u202eement\u2069");
    expect(pauseCopy("drift", cause("drift", "post_close", "a||:0"), graph).body).toBe(
      "\u2068Impl\u202eement\u2069’s session kept working after its step closed.",
    );
    expect(
      pauseCopy("failure_path", cause("failure_path", "attempts_exhausted", "ls\u202e"), graph)
        .body,
    ).toBe("Missing evidence: \u2068ls\u202e\u2069.");
    expect(
      pauseCopy(
        "failure_path",
        cause("failure_path", "attempts_exhausted:ls\u202e", "a||:0"),
        graph,
      ).body,
    ).toBe("Missing evidence: \u2068ls\u202e\u2069.");
    expect(pauseCopy("infra", cause("infra", "recovery.restarting", "a||:0"), graph).body).toBe(
      "Coral is restarting \u2068Impl\u202eement\u2069 from its last handoff.",
    );
  });

  it("keeps its client-only copy in curly apostrophes and the server's copy byte for byte", () => {
    // WHY: the web's own copy uses ’, while the alert copy must equal the server's exactly.
    expect(LOAD_FAILED_TEXT).toBe("This run can’t be loaded. You can still cancel it.");
    expect(PAUSE_MESSAGES.plan_limit).toBe("A step reached its plan's usage limit.");
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
    ["attempts_exhausted:pytest -q", "implement||a4:2:0"],
    ["engine.load_failed", ""],
    ["approve_change is waiting for implement, which can no longer run.", "implement"],
    ["anchor_archived", ""],
    ["anchor_deleted", ""],
    ["pending_input", "implement||a4:2:0"],
    ["post_close", "implement||a4:1:0"],
    ["infra.host_offline", "implement||a4:2:0"],
    ["recovery.restarting", "implement||a4:2:0"],
    ["infra.runner_lost", "implement||a4:2:0"],
    ["recovery.runner_alive", "implement||a4:2:0"],
    ["restart:session.host_offline", "implement||a4:2:0"],
    ["restart:workspace.head_moved", "implement||a4:2:0"],
    ["restart:workspace.tree_changed", "implement||a4:2:0"],
    ["session.host_unsupported", "implement||a4:2:0"],
    ["blocked", "implement||a4:2:0"],
    ["session.closed", "implement||a4:2:0"],
    ["session.runner_status_unknown", "implement||a4:2:0"],
  ];
  const OWNER: Record<string, PauseReasonName> = {
    attempts_exhausted: "failure_path",
    "attempts_exhausted:pytest -q": "failure_path",
    "engine.load_failed": "failure_path",
    anchor_archived: "drift",
    anchor_deleted: "drift",
    pending_input: "drift",
    post_close: "drift",
    "infra.host_offline": "infra",
    "recovery.restarting": "infra",
    "infra.runner_lost": "infra",
    "recovery.runner_alive": "infra",
    "restart:session.host_offline": "failure_path",
    "restart:workspace.head_moved": "failure_path",
    "restart:workspace.tree_changed": "failure_path",
    "session.host_unsupported": "failure_path",
    blocked: "failure_path",
    "session.closed": "failure_path",
    "session.runner_status_unknown": "infra",
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

describe("stallSentences", () => {
  const STEP = isolated("Implement");

  it("names the step in each thing that stalls it, in one order", () => {
    // WHY: the banner and the step list say the same sentences about a step.
    expect(stallSentences(STEP, { pendingInput: true, drift: true, decisionOpen: true })).toEqual([
      `Someone typed into ${STEP}’s session.`,
      `${STEP}’s session was changed outside Coral.`,
      `Waiting for the orchestrator to choose at ${STEP}.`,
    ]);
    expect(stallSentences(STEP, {})).toEqual([]);
  });

  it("leaves out the plain typed-into sentence when a cause already says it", () => {
    // WHY: the cause names the same event in longer words; other causes do not.
    const typedInto = cause("drift", "pending_input", "implement||a4:2:0");
    const archived = cause("drift", "anchor_archived");
    expect(stallSentences(STEP, { pendingInput: true, drift: true, causes: [typedInto] })).toEqual([
      `${STEP}’s session was changed outside Coral.`,
    ]);
    expect(stallSentences(STEP, { pendingInput: true, causes: [archived] })).toEqual([
      `Someone typed into ${STEP}’s session.`,
    ]);
  });
});

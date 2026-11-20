import { describe, expect, it } from "vitest";
import type { RunHeader } from "../api/generated/coralApi";
import type { RunStatus } from "../api/runsApi";
import { runStatus } from "./runStatus";

/** Every status the generated union names; `tsc` fails here when the server adds one. */
const STATUSES = [
  "starting",
  "running",
  "paused",
  "completed",
  "failed",
  "cancelled",
] as const satisfies readonly RunStatus[];
const COVERED: [Exclude<RunHeader["status"], (typeof STATUSES)[number]>] extends [never]
  ? true
  : false = true;

describe("runStatus", () => {
  it("lists every status of the generated union", () => {
    // WHY: the real check is `tsc`: COVERED's type is `false` once the generated union gains a
    // status, so the file no longer compiles. At run time this only keeps the constant used.
    expect(COVERED).toBe(true);
  });

  it.each<[string, string, string | null, readonly string[] | null, string, string]>([
    ["starting", "starting", null, null, "Starting", "blue"],
    ["running", "running", null, [], "Running", "blue"],
    ["running with an open gate", "running", null, ["approve||:1"], "Needs you", "yellow"],
    ["running in the list, with no view", "running", null, null, "Running", "blue"],
    ["paused by its owner", "paused", "user", [], "Paused: by you", "yellow"],
    ["paused at an open gate", "paused", "user", ["approve||:1"], "Paused: by you", "yellow"],
    ["paused at its activation cap", "paused", "budget", null, "Paused: activation cap", "yellow"],
    ["paused for a reason it cannot name", "paused", "solar_flare", null, "Paused", "yellow"],
    ["paused with no reason", "paused", null, null, "Paused", "yellow"],
    ["completed", "completed", null, [], "Completed", "green"],
    ["failed", "failed", null, [], "Failed", "red"],
    ["cancelled", "cancelled", null, [], "Cancelled", "gray"],
    ["a status it does not know", "archived", null, [], "Unknown", "gray"],
  ])("shows %s", (_name, status, pauseReason, openGates, text, tone) => {
    // WHY: one pill text per status; "Needs you" only for a running run with a gate open.
    expect(runStatus(status, pauseReason, openGates)).toMatchObject({ text, tone });
  });

  it("names each status's kind, so a view can tell Needs you from Running", () => {
    // WHY: a paused run keeps its open gates, and Paused must win over Needs you.
    expect(STATUSES.map((status) => runStatus(status, "user", ["g"]).kind)).toEqual([
      "starting",
      "needs_you",
      "paused",
      "completed",
      "failed",
      "cancelled",
    ]);
    expect(runStatus("running", null, []).kind).toBe("running");
    expect(runStatus("archived", null, null).kind).toBe("unknown");
  });

  it("gives a finished run its own name whatever gates it lists", () => {
    // WHY: the row wins over the view once the run has finished.
    expect(runStatus("completed", null, ["approve||:1"]).text).toBe("Completed");
  });
});

describe("runStatus over every status, pause reason and gate list", () => {
  const LABELS: Readonly<Record<NonNullable<RunHeader["pause_reason"]>, string>> = {
    user: "by you",
    failure_path: "step failed",
    infra: "infrastructure",
    plan_limit: "plan limit",
    auth: "sign-in needed",
    budget: "activation cap",
    rejected_calls: "refused calls",
    liveness: "step waiting",
    drift: "session changed",
    authority_revoked: "account access revoked",
    engine_upgrade: "Coral upgraded",
    gate: "gate",
    merge_conflict: "merge conflict",
  };
  // Names an object lookup would find on its prototype, and reasons a newer server may send.
  const ODD_NAMES = ["", "constructor", "__proto__", "toString", "hasOwnProperty", "solar_flare"];
  const REASONS: (string | null)[] = [...Object.keys(LABELS), ...ODD_NAMES, null];
  const GATES: (readonly string[] | null)[] = [null, [], ["approve||:1"], ["a||:1", "b||:1"]];
  const NAMED = {
    starting: "Starting",
    completed: "Completed",
    failed: "Failed",
    cancelled: "Cancelled",
  };

  function expected(status: string, reason: string | null, gates: readonly string[] | null) {
    if (status === "running") return gates !== null && gates.length > 0 ? "Needs you" : "Running";
    if (status === "paused") {
      return reason !== null && Object.hasOwn(LABELS, reason)
        ? `Paused: ${LABELS[reason as keyof typeof LABELS]}`
        : "Paused";
    }
    return Object.hasOwn(NAMED, status) ? NAMED[status as keyof typeof NAMED] : "Unknown";
  }

  it("names every combination by the status alone, except running with gates and paused", () => {
    // WHY: one rule per status; a stale pause reason or open gate never leaks into another pill.
    const statuses = [...STATUSES, "archived", "RUNNING", ...ODD_NAMES];
    for (const status of statuses) {
      for (const reason of REASONS) {
        for (const gates of GATES) {
          const pill = runStatus(status, reason, gates);
          expect(pill.text, `${status} / ${reason} / ${JSON.stringify(gates)}`).toBe(
            expected(status, reason, gates),
          );
          expect(pill.kind === "unknown").toBe(pill.text === "Unknown");
          expect(pill.kind === "needs_you").toBe(pill.text === "Needs you");
        }
      }
    }
  });
});

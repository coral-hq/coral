import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/sessionsApi";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import { CONTRACT_GRAPH, CONTRACT_OUTCOME } from "../fixtures/runViewContract";
import {
  answerGate,
  CoralRequestError,
  getRun,
  getRunGraph,
  getRunOutcome,
  listRuns,
  postRunAction,
  runActionKey,
  runGraphQueryKey,
  runOutcomeQueryKey,
  runQueryKey,
  runsListPrefixKey,
  runsListQueryKey,
  runStreamUrl,
  runViewQueryKey,
  startRun,
  type RunFilters,
} from "./runsApi";
import type { RunSummary, StartRunRequest } from "./generated/coralApi";

const RUN_ID = "84170e76f35c7a90d1280a24a7230fc9";

const SUMMARY: RunSummary = {
  run_id: RUN_ID,
  workflow_id: "a".repeat(32),
  version_id: "b".repeat(32),
  title: "Ship the bridge",
  status: "running",
  pause_reason: null,
  created_at: 1_767_268_000,
  updated_at: 1_767_268_900,
  finished_at: null,
  activation_count: 3,
  allowed_actions: ["pause", "cancel"],
  spend: null,
  run_branch: "coral/r-0a1b2c3d4e5f/base",
};

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

const envelope = (code: string, message: string, details: unknown = null) => ({
  error: { code, message, details },
});

const SCOPE = JSON.stringify(["http://localhost", "/", "alice"]);
const OTHER_VIEWER = JSON.stringify(["http://localhost", "/", "bob"]);
const ALL_RUNS: RunFilters = { statuses: [], workflowId: null };

/** The request `authenticatedFetch` was called with, by call index. */
function sent(call = 0): { url: string; init: RequestInit } {
  const [url, init] = authenticatedFetch.mock.calls[call] as [string, RequestInit | undefined];
  return { url, init: init ?? {} };
}

beforeEach(() => authenticatedFetch.mockReset());

describe("run query keys", () => {
  it("files every run query under its viewer and server scope", () => {
    // WHY: a cached run must never be shown to another viewer or read from another server.
    const filters: RunFilters = { statuses: ["paused"], workflowId: "w1" };
    expect(runQueryKey(SCOPE, RUN_ID)).toEqual(["coral-run", SCOPE, RUN_ID]);
    expect(runViewQueryKey(SCOPE, RUN_ID)).toEqual(["coral-run-view", SCOPE, RUN_ID]);
    expect(runGraphQueryKey(SCOPE, RUN_ID)).toEqual(["coral-run-graph", SCOPE, RUN_ID]);
    expect(runOutcomeQueryKey(SCOPE, RUN_ID)).toEqual(["coral-run-outcome", SCOPE, RUN_ID]);
    expect(runsListQueryKey(SCOPE, filters)).toEqual(["coral-runs", SCOPE, filters]);
    // Every filtered list starts with the prefix a start or an action invalidates.
    expect(runsListQueryKey(SCOPE, filters).slice(0, 2)).toEqual(runsListPrefixKey(SCOPE));
    expect(runActionKey(SCOPE, RUN_ID)).toEqual(["coral-run-action", SCOPE, RUN_ID]);
  });

  it("gives another viewer other keys", () => {
    // WHY: a viewer change starts from an empty cache rather than the last viewer's runs.
    for (const key of [runQueryKey, runViewQueryKey, runGraphQueryKey, runOutcomeQueryKey]) {
      expect(key(OTHER_VIEWER, RUN_ID)).not.toEqual(key(SCOPE, RUN_ID));
    }
    expect(runsListQueryKey(OTHER_VIEWER, ALL_RUNS)).not.toEqual(runsListQueryKey(SCOPE, ALL_RUNS));
    expect(runActionKey(OTHER_VIEWER, RUN_ID)).not.toEqual(runActionKey(SCOPE, RUN_ID));
  });

  it("files one status set under one list key, in any order and with repeats", () => {
    // WHY: the same filters must share one cache entry and one poll, however the URL lists them.
    const key = runsListQueryKey(SCOPE, { statuses: ["running", "paused"], workflowId: "w1" });
    expect(
      runsListQueryKey(SCOPE, { statuses: ["paused", "running", "paused"], workflowId: "w1" }),
    ).toEqual(key);
    expect(key).toEqual([
      "coral-runs",
      SCOPE,
      { statuses: ["paused", "running"], workflowId: "w1" },
    ]);
    expect(runsListQueryKey(SCOPE, { statuses: ["paused"], workflowId: "w1" })).not.toEqual(key);
    expect(
      runsListQueryKey(SCOPE, { statuses: ["running", "paused"], workflowId: null }),
    ).not.toEqual(key);
  });

  it("keeps the detail and the streamed view under different keys", () => {
    // WHY: only the stream writes the view; a detail refetch must not overwrite it.
    expect(runViewQueryKey(SCOPE, RUN_ID)).not.toEqual(runQueryKey(SCOPE, RUN_ID));
  });
});

describe("runs client", () => {
  it("reads a run's detail from its route", async () => {
    // WHY: the Inbox card decides its buttons from the detail's allowed_actions.
    authenticatedFetch.mockResolvedValue(json({ ...SUMMARY, allowed_actions: ["cancel"] }));
    const run = await getRun(RUN_ID);
    expect(run.allowed_actions).toEqual(["cancel"]);
    const [url, init] = authenticatedFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe(`/v1/coral/runs/${RUN_ID}`);
    expect(init.method).toBeUndefined();
  });

  it.each(["pause", "resume", "cancel"] as const)(
    "posts an empty JSON object to the run's :%s route",
    async (action) => {
      // WHY: Coral POSTs take only JSON bodies; resume without a cap sends nothing else.
      authenticatedFetch.mockResolvedValue(json({ ...SUMMARY, allowed_actions: [] }));
      const summary = await postRunAction(RUN_ID, action);
      expect(summary.allowed_actions).toEqual([]);
      const [url, init] = authenticatedFetch.mock.calls[0] as [string, RequestInit];
      expect(url).toBe(`/v1/coral/runs/${RUN_ID}:${action}`);
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
      expect(JSON.parse(init.body as string)).toEqual({});
    },
  );

  it("escapes the run id in the path", async () => {
    // WHY: the id comes from an alert payload; it must stay one path segment.
    authenticatedFetch.mockImplementation(() => Promise.resolve(json(SUMMARY)));
    await getRun("../a/b?c#d");
    await postRunAction("../a/b?c#d", "cancel");
    expect(authenticatedFetch.mock.calls.map(([url]) => url)).toEqual([
      "/v1/coral/runs/..%2Fa%2Fb%3Fc%23d",
      "/v1/coral/runs/..%2Fa%2Fb%3Fc%23d:cancel",
    ]);
  });

  it.each(["", ".", ".."])(
    "refuses the run id %j as not found without a request",
    async (runId) => {
      // WHY: URL parsing resolves dot segments, so these ids would leave the run's path.
      await expect(getRun(runId)).rejects.toMatchObject({ status: 404, code: "not_found" });
      await expect(postRunAction(runId, "cancel")).rejects.toBeInstanceOf(ApiError);
      expect(authenticatedFetch).not.toHaveBeenCalled();
    },
  );

  it("reads a refusal envelope into an ApiError with its code, status and Retry-After", async () => {
    // WHY: callers pick their text by status and code, and back off as the server asks.
    authenticatedFetch.mockResolvedValue(
      json(envelope("server_busy", "The server is busy; try again."), 503, { "Retry-After": "1" }),
    );
    const error = await postRunAction(RUN_ID, "resume").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "server_busy",
      message: "The server is busy; try again.",
      retryAfterMs: 1_000,
    });
  });

  it("keeps a conflict's own message", async () => {
    // WHY: a 409 explains the run's state in the server's words.
    authenticatedFetch.mockResolvedValue(
      json(
        envelope("illegal_transition", "The run is completed.", {
          status: "completed",
          pause_reason: null,
        }),
        409,
      ),
    );
    await expect(postRunAction(RUN_ID, "cancel")).rejects.toMatchObject({
      status: 409,
      code: "illegal_transition",
      message: "The run is completed.",
      retryAfterMs: null,
      details: { status: "completed", pause_reason: null },
    });
  });

  it("reads the fixed run 404 and a routing 404 alike by status", async () => {
    // WHY: an unknown run and a server without the runs API both mean "not available".
    authenticatedFetch
      .mockResolvedValueOnce(json(envelope("not_found", "Run not found."), 404))
      .mockResolvedValueOnce(json({ detail: "Not Found" }, 404));
    await expect(getRun(RUN_ID)).rejects.toMatchObject({ status: 404, code: "not_found" });
    await expect(getRun(RUN_ID)).rejects.toMatchObject({ status: 404, code: null });
  });
});

describe("Coral refusals", () => {
  it("keeps a refusal's details, reason included", async () => {
    // WHY: a gate answer's refusal says why only in details.reason.
    authenticatedFetch.mockResolvedValue(
      json(
        envelope("illegal_transition", "The run is paused; resume it, then answer.", {
          reason: "run_paused",
        }),
        409,
      ),
    );
    const error = await postRunAction(RUN_ID, "resume").catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CoralRequestError);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      name: "CoralRequestError",
      status: 409,
      code: "illegal_transition",
      message: "The run is paused; resume it, then answer.",
      details: { reason: "run_paused" },
    });
  });

  it("keeps Retry-After beside the details of a busy refusal", async () => {
    // WHY: a busy run is retried when the server says, with the reason still readable.
    authenticatedFetch.mockResolvedValue(
      json(envelope("server_busy", "The run is busy; try again.", { reason: "run_busy" }), 503, {
        "Retry-After": "2",
      }),
    );
    await expect(getRun(RUN_ID)).rejects.toMatchObject({
      status: 503,
      code: "server_busy",
      retryAfterMs: 2_000,
      details: { reason: "run_busy" },
    });
  });

  it("reads a Coral refusal without details as one with none", async () => {
    // WHY: Coral always sends details, null when it has nothing more to say.
    authenticatedFetch.mockResolvedValue(json(envelope("not_found", "Run not found."), 404));
    const error = await getRun(RUN_ID).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CoralRequestError);
    expect((error as CoralRequestError).details).toBeNull();
  });

  it.each<[string, () => Response]>([
    [
      "Omnigent's envelope, which has no details",
      () => json({ error: { code: "not_found", message: "Not found." } }, 404),
    ],
    ["FastAPI's detail", () => json({ detail: "Not Found" }, 404)],
    [
      "an envelope whose details are not an object",
      () => json({ error: { code: "x", message: "y", details: ["reason"] } }, 409),
    ],
    ["no body", () => new Response(null, { status: 502, statusText: "Bad Gateway" })],
    ["an HTML body", () => new Response("<html>proxy</html>", { status: 502 })],
  ])("reads %s as a plain ApiError", async (_name, answer) => {
    // WHY: only Coral's own envelope carries details a caller may branch on.
    authenticatedFetch.mockResolvedValue(answer());
    const error = await getRun(RUN_ID).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(CoralRequestError);
  });

  it("reads the message and code exactly as a plain ApiError would", async () => {
    // WHY: callers that branch on status, code and message keep working on the subclass.
    authenticatedFetch.mockResolvedValue(
      json(envelope("stale_visit", "This gate was asked again; answer the latest one."), 409),
    );
    await expect(getRun(RUN_ID)).rejects.toMatchObject({
      status: 409,
      code: "stale_visit",
      message: "This gate was asked again; answer the latest one.",
      details: null,
    });
  });
});

describe("runs list", () => {
  const PAGE = { data: [SUMMARY], next_cursor: "c2" };

  it("reads the first page of every run, 25 at a time", async () => {
    // WHY: the runs table pages through the caller's history in fixed pages.
    authenticatedFetch.mockResolvedValue(json(PAGE));
    expect(await listRuns(ALL_RUNS)).toEqual(PAGE);
    expect(sent().url).toBe("/v1/coral/runs?limit=25");
  });

  it("sends each status filter as its own parameter, the workflow and the cursor", async () => {
    // WHY: the server reads repeated `status` values; a joined list would match nothing.
    authenticatedFetch.mockResolvedValue(json(PAGE));
    await listRuns({ statuses: ["running", "paused"], workflowId: "w&1" }, "1:900:a b");
    const url = new URL(sent().url, "http://local");
    expect(url.pathname).toBe("/v1/coral/runs");
    expect(url.searchParams.getAll("status")).toEqual(["running", "paused"]);
    expect(url.searchParams.get("workflow_id")).toBe("w&1");
    expect(url.searchParams.get("after")).toBe("1:900:a b");
    expect(url.searchParams.get("limit")).toBe("25");
    expect([...url.searchParams.keys()]).toEqual([
      "limit",
      "status",
      "status",
      "workflow_id",
      "after",
    ]);
  });

  it("passes the abort signal on", async () => {
    // WHY: a filter change cancels the page read it replaces.
    authenticatedFetch.mockResolvedValue(json(PAGE));
    const controller = new AbortController();
    await listRuns(ALL_RUNS, undefined, controller.signal);
    expect(sent().init.signal).toBe(controller.signal);
  });
});

describe("run graph, outcome and stream", () => {
  it("reads the run's pinned graph", async () => {
    // WHY: the run view draws the graph the run was started on, not the workflow's latest.
    authenticatedFetch.mockResolvedValue(json(CONTRACT_GRAPH));
    expect(await getRunGraph(RUN_ID)).toEqual(CONTRACT_GRAPH);
    expect(sent().url).toBe(`/v1/coral/runs/${RUN_ID}/graph`);
    expect(sent().init.method).toBeUndefined();
  });

  it("reads the run's outcome", async () => {
    // WHY: the outcome panel shows the server's checkout command verbatim.
    authenticatedFetch.mockResolvedValue(json(CONTRACT_OUTCOME));
    const outcome = await getRunOutcome(RUN_ID);
    expect(outcome.checkout.command).toBe(CONTRACT_OUTCOME.checkout.command);
    expect(sent().url).toBe(`/v1/coral/runs/${RUN_ID}/outcome`);
  });

  it("names the run's stream route", () => {
    // WHY: the stream client opens this path itself, with its own headers.
    expect(runStreamUrl(RUN_ID)).toBe(`/v1/coral/runs/${RUN_ID}/stream`);
    expect(runStreamUrl("a/b?c")).toBe("/v1/coral/runs/a%2Fb%3Fc/stream");
  });

  it.each(["", ".", ".."])(
    "refuses the run id %j for the graph, outcome and stream",
    async (id) => {
      // WHY: URL parsing resolves dot segments, so these ids would leave the run's path.
      await expect(getRunGraph(id)).rejects.toMatchObject({ status: 404 });
      await expect(getRunOutcome(id)).rejects.toMatchObject({ status: 404 });
      expect(() => runStreamUrl(id)).toThrow(ApiError);
      expect(authenticatedFetch).not.toHaveBeenCalled();
    },
  );
});

describe("gate answers", () => {
  const ANSWER = { visit_token: "approve_change||a4:1:1", outcome: "approve", note: "Ship it." };

  it("posts the answer to the gate's route as JSON", async () => {
    // WHY: the run view answers a gate through the runs route, by its visit token.
    authenticatedFetch.mockResolvedValue(json({ result: "accepted" }));
    expect(await answerGate(RUN_ID, "approve_change", ANSWER)).toEqual({ result: "accepted" });
    const { url, init } = sent();
    expect(url).toBe(`/v1/coral/runs/${RUN_ID}/gates/approve_change:answer`);
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual(ANSWER);
  });

  it("escapes the run and node ids in the path", async () => {
    // WHY: each id must stay one path segment.
    authenticatedFetch.mockResolvedValue(json({ result: "duplicate" }));
    await answerGate("r/1", "a:b/c?d", ANSWER);
    expect(sent().url).toBe("/v1/coral/runs/r%2F1/gates/a%3Ab%2Fc%3Fd:answer");
  });

  it.each(["", ".", ".."])("refuses the node id %j without a request", async (nodeId) => {
    // WHY: URL parsing resolves dot segments, so these ids would leave the gate's path.
    await expect(answerGate(RUN_ID, nodeId, ANSWER)).rejects.toMatchObject({ status: 404 });
    await expect(answerGate(nodeId, "approve_change", ANSWER)).rejects.toMatchObject({
      status: 404,
    });
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("keeps a refused answer's reason", async () => {
    // WHY: the gate card picks its text and whether to keep the form from the reason.
    authenticatedFetch.mockResolvedValue(
      json(
        envelope("validation_failed", "Choose one of: approve, reject.", {
          reason: "invalid_answer",
        }),
        422,
      ),
    );
    await expect(answerGate(RUN_ID, "approve_change", ANSWER)).rejects.toMatchObject({
      status: 422,
      details: { reason: "invalid_answer" },
    });
  });
});

describe("starting a run", () => {
  const REQUEST: StartRunRequest = {
    workflow_id: "a".repeat(32),
    start_key: "0f8e2b7c-7d1a-4c3e-9a4b-2d6f1e0c9b8a",
    host_id: "host-1",
    repo_path: "/home/alice/team's repo",
  };

  it.each([201, 200])(
    "posts the start request and reads the run it answers with %i",
    async (status) => {
      // WHY: 201 is a new run and 200 the run the same start key began; both open the run.
      authenticatedFetch.mockResolvedValue(json(SUMMARY, status));
      expect(await startRun(REQUEST)).toEqual(SUMMARY);
      const { url, init } = sent();
      expect(url).toBe("/v1/coral/runs");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
      expect(JSON.parse(init.body as string)).toEqual(REQUEST);
    },
  );

  it("keeps a refused start's code and message", async () => {
    // WHY: the start dialog picks its text by status and code.
    authenticatedFetch.mockResolvedValue(
      json(envelope("not_a_git_repo", "Not a git repository."), 400),
    );
    await expect(startRun(REQUEST)).rejects.toMatchObject({
      status: 400,
      code: "not_a_git_repo",
    });
  });
});

describe("every client's refusals", () => {
  const GATE_ANSWER = { visit_token: "approve_change||a4:1:1", outcome: "approve" };
  const START: StartRunRequest = {
    workflow_id: "a".repeat(32),
    start_key: "0f8e2b7c-7d1a-4c3e-9a4b-2d6f1e0c9b8a",
    host_id: "host-1",
    repo_path: "/home/alice/repo",
  };
  const CLIENTS: [string, () => Promise<unknown>][] = [
    ["getRun", () => getRun(RUN_ID)],
    ["listRuns", () => listRuns(ALL_RUNS)],
    ["getRunGraph", () => getRunGraph(RUN_ID)],
    ["getRunOutcome", () => getRunOutcome(RUN_ID)],
    ["postRunAction", () => postRunAction(RUN_ID, "pause")],
    ["answerGate", () => answerGate(RUN_ID, "approve_change", GATE_ANSWER)],
    ["startRun", () => startRun(START)],
  ];
  const REFUSALS: [number, string, Record<string, string>, number | null][] = [
    [404, "not_found", {}, null],
    [409, "illegal_transition", {}, null],
    [422, "validation_failed", {}, null],
    [429, "stream_limit", { "Retry-After": "7" }, 7_000],
    [503, "server_busy", { "Retry-After": "1" }, 1_000],
  ];

  it.each(
    CLIENTS.flatMap(([name, call]) =>
      REFUSALS.map(([status, code, headers, retryAfterMs]) => ({
        name,
        call,
        status,
        code,
        headers,
        retryAfterMs,
      })),
    ),
  )("$name keeps a Coral $status's code, details and Retry-After", async (refusal) => {
    // WHY: every view branches on status, code and details.reason, whichever route refused.
    const { call, status, code, headers, retryAfterMs } = refusal;
    authenticatedFetch.mockResolvedValue(
      json(envelope(code, "No.", { reason: "r" }), status, headers),
    );
    const error = await call().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(CoralRequestError);
    expect(error).toMatchObject({
      status,
      code,
      message: "No.",
      details: { reason: "r" },
      retryAfterMs,
    });
  });

  const ODD: [string, () => Response, Record<string, unknown>][] = [
    [
      "no body",
      () => new Response(null, { status: 502, statusText: "Bad Gateway" }),
      { status: 502, code: null, message: "502 Bad Gateway" },
    ],
    [
      "an HTML page with a Retry-After that is not a number",
      () => new Response("<html>busy</html>", { status: 503, headers: { "Retry-After": "soon" } }),
      { status: 503, code: null, retryAfterMs: null },
    ],
    [
      "an envelope without the details key",
      () => json({ error: { code: "illegal_transition", message: "No." } }, 409),
      { status: 409, code: "illegal_transition", message: "No." },
    ],
    ["a JSON null", () => json(null, 404), { status: 404, code: null }],
    ["a string error", () => json({ error: "busy" }, 503), { status: 503, code: null }],
    [
      "an envelope whose code is not a string",
      () => json({ error: { code: 7, message: "No.", details: null } }, 422),
      { status: 422 },
    ],
    [
      "a cut-off JSON body",
      () => new Response('{"error": {"code": "not_found"', { status: 404 }),
      { status: 404, code: null },
    ],
  ];

  it.each(
    CLIENTS.flatMap(([name, call]) =>
      ODD.map(([odd, answer, fields]) => ({ name, call, odd, answer, fields })),
    ),
  )("$name reads $odd as a plain ApiError", async ({ call, answer, fields }) => {
    // WHY: only Coral's own envelope carries details; anything else keeps its status line.
    authenticatedFetch.mockResolvedValue(answer());
    const error = await call().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).not.toBeInstanceOf(CoralRequestError);
    expect(error).toMatchObject(fields);
  });

  it.each(CLIENTS)(
    "%s keeps the details of a busy refusal whose Retry-After is not a number",
    async (_name, call) => {
      // WHY: a malformed hint falls back to the caller's own backoff; the reason still reads.
      authenticatedFetch.mockResolvedValue(
        json(envelope("server_busy", "Busy.", { reason: "run_busy" }), 503, {
          "Retry-After": "soon",
        }),
      );
      await expect(call()).rejects.toMatchObject({
        name: "CoralRequestError",
        retryAfterMs: null,
        details: { reason: "run_busy" },
      });
    },
  );

  it("sends a retried start's key unchanged and makes one request per call", async () => {
    // WHY: a retry with the same key replays the first run (200); a key the client made up would start a second one.
    authenticatedFetch
      .mockResolvedValueOnce(json(envelope("server_busy", "Busy."), 503, { "Retry-After": "1" }))
      .mockResolvedValueOnce(json(SUMMARY, 200))
      .mockResolvedValueOnce(json({ ...SUMMARY, run_id: "f".repeat(32) }, 201));
    await expect(startRun(START)).rejects.toMatchObject({ status: 503, retryAfterMs: 1_000 });
    expect(await startRun(START)).toEqual(SUMMARY);
    const otherHost = {
      ...START,
      host_id: "host-2",
      start_key: "5d1c0f3e-2a4b-4c6d-8e9f-0a1b2c3d4e5f",
    };
    expect((await startRun(otherHost)).run_id).toBe("f".repeat(32));
    const bodies = authenticatedFetch.mock.calls.map(([, init]) =>
      JSON.parse((init as RequestInit).body as string),
    );
    expect(bodies).toEqual([START, START, otherHost]);
  });
});

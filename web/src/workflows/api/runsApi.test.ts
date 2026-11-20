import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/sessionsApi";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import { getRun, postRunAction, runQueryKey } from "./runsApi";
import type { RunSummary } from "./generated/coralApi";

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

beforeEach(() => authenticatedFetch.mockReset());

describe("runs client", () => {
  it("keys a run's query by its id", () => {
    expect(runQueryKey(RUN_ID)).toEqual(["coral-run", RUN_ID]);
  });

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

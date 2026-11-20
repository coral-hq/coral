import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { ApiError } from "@/lib/sessionsApi";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
const viewer = vi.hoisted(() => ({ id: "alice" as string | null }));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => viewer.id,
  useIdentityReady: () => true,
}));

import type { RunDetail, RunHeader, RunView } from "../api/generated/coralApi";
import { jsonResponse } from "../fixtures/runStreamServer";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
} from "../fixtures/runViewContract";
import { applyViewPatch, type JsonObject } from "../stream/viewPatch";
import type { StalenessMarks } from "./detailStaleness";
import {
  DETAIL_POLL_MS,
  DETAIL_REFRESH_MIN_MS,
  useDetailFailure,
  useRunDetail,
  type RunDetailStream,
} from "./useRunDetail";

const RUN_ID = CONTRACT_DETAIL_GATE_PASS1.run_id;
const DETAIL_URL = `/v1/coral/runs/${RUN_ID}`;
const PASS1_VIEW = CONTRACT_DETAIL_GATE_PASS1.view!;
// The second gate's view: its gate and slot are ones the first gate's detail lacks.
const PASS2_VIEW = CONTRACT_DETAIL_GATE_PASS2.view!;
const RUNNING: RunHeader = {
  status: "running",
  pause_reason: null,
  version: 6,
  finished_at: null,
  allowed_actions: ["pause", "cancel"],
  load_error: null,
};
const NOTHING: StalenessMarks = { view: null, header: null };

/** Each detail read's answer in turn (the last repeats); a promise holds the read open. */
let answers: (RunDetail | Promise<RunDetail>)[] = [];

function serveDetails(...next: (RunDetail | Promise<RunDetail>)[]) {
  answers = next;
  authenticatedFetch.mockImplementation(async (url: string) => {
    if (url !== DETAIL_URL) return jsonResponse(404, {});
    const answer = answers.length > 1 ? answers.shift()! : answers[0]!;
    return jsonResponse(200, await answer);
  });
}

const reads = () => authenticatedFetch.mock.calls.filter(([url]) => url === DETAIL_URL).length;

function held(): { promise: Promise<RunDetail>; release: (detail: RunDetail) => void } {
  let release: (detail: RunDetail) => void = () => {};
  const promise = new Promise<RunDetail>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

function renderDetail(initial: RunDetailStream = NOTHING) {
  const client = new QueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return renderHook(({ stream }: { stream: RunDetailStream }) => useRunDetail(RUN_ID, stream), {
    initialProps: { stream: initial },
    wrapper,
  });
}

function patched(view: RunView, patch: { op: string; path: string; value?: unknown }[]): RunView {
  return applyViewPatch(view as unknown as JsonObject, patch) as unknown as RunView;
}

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

beforeEach(() => {
  vi.useFakeTimers();
  serveDetails(CONTRACT_DETAIL_GATE_PASS1);
});

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
  viewer.id = "alice";
  vi.useRealTimers();
});

describe("useRunDetail", () => {
  it("reads the detail once the viewer is known", async () => {
    // WHY: a run read before the viewer is known would be filed under no one's scope.
    viewer.id = null;
    const { result, rerender } = renderDetail();
    await run(1_000);
    expect(reads()).toBe(0);
    viewer.id = "alice";
    rerender({ stream: NOTHING });
    await run();
    expect(reads()).toBe(1);
    expect(result.current.data?.run_id).toBe(RUN_ID);
  });

  it("rereads every 30 s for spend while the run is unfinished, never once it ends", async () => {
    // WHY: spend moves while a run works; a finished run's detail no longer changes.
    const { rerender } = renderDetail({ view: PASS1_VIEW, header: RUNNING });
    await run();
    expect(reads()).toBe(1);
    await run(DETAIL_POLL_MS);
    expect(reads()).toBe(2);
    rerender({
      stream: {
        view: PASS1_VIEW,
        header: { ...RUNNING, status: "completed", allowed_actions: [] },
      },
    });
    await run(3 * DETAIL_POLL_MS);
    expect(reads()).toBe(2);
  });

  it("rereads a stale detail on a trigger, at most once per 2 s", async () => {
    // WHY: a gate or slot the detail lacks needs its token and session; a burst stays one read.
    const { rerender } = renderDetail();
    await run();
    expect(reads()).toBe(1);
    rerender({ stream: { view: PASS2_VIEW, header: RUNNING } });
    await run();
    expect(reads()).toBe(2);
    rerender({ stream: { view: PASS2_VIEW, header: { ...RUNNING } } });
    await run(DETAIL_REFRESH_MIN_MS - 1);
    expect(reads()).toBe(2);
    await run(1);
    expect(reads()).toBe(3);
  });

  it("leaves a mismatch the reread kept until the next trigger, so it never loops", async () => {
    // WHY: the server can lag the stream for a while; polling it every 2 s would hammer it.
    const { rerender } = renderDetail();
    await run();
    rerender({ stream: { view: PASS2_VIEW, header: RUNNING } });
    await run();
    expect(reads()).toBe(2);
    await run(DETAIL_POLL_MS - 1_000);
    expect(reads()).toBe(2);
    const progressed = patched(PASS2_VIEW, [
      { op: "replace", path: "/activations/4/status", value: "evaluating" },
    ]);
    rerender({ stream: { view: progressed, header: RUNNING } });
    await run(500);
    expect(reads()).toBe(2);
    const slotMoved = patched(progressed, [
      { op: "replace", path: "/slots/1/status", value: "working" },
    ]);
    rerender({ stream: { view: slotMoved, header: RUNNING } });
    await run();
    expect(reads()).toBe(3);
  });

  it("checks the first detail against a view that came before it", async () => {
    // WHY: a snapshot can land before the detail, which the server may have read just before
    // a gate opened; only that first detail answers the early trigger, so it cannot loop.
    const first = held();
    serveDetails(first.promise, CONTRACT_DETAIL_GATE_PASS1);
    renderDetail({ view: PASS2_VIEW, header: RUNNING });
    await run();
    expect(reads()).toBe(1);
    first.release(CONTRACT_DETAIL_GATE_PASS1);
    await run();
    expect(reads()).toBe(2);
    await run(DETAIL_POLL_MS - 1_000);
    expect(reads()).toBe(2);
  });

  it("stops rereading once the run is gone or its stream refused", async () => {
    // WHY: a dead-end page has nothing to refresh.
    const { rerender } = renderDetail({ view: PASS1_VIEW, header: RUNNING });
    await run();
    rerender({ stream: { view: PASS1_VIEW, header: RUNNING, status: "not_found" } });
    await run(3 * DETAIL_POLL_MS);
    expect(reads()).toBe(1);
    serveDetails(CONTRACT_DETAIL_GATE_PASS1);
    rerender({ stream: { view: PASS1_VIEW, header: RUNNING, status: "failed" } });
    await run(3 * DETAIL_POLL_MS);
    expect(reads()).toBe(1);
  });

  it("stops polling a detail that answered 404", async () => {
    // WHY: the run is not the caller's; asking again every 30 s changes nothing.
    authenticatedFetch.mockImplementation(async () =>
      jsonResponse(404, { error: { code: "not_found", message: "Run not found.", details: null } }),
    );
    renderDetail({ view: PASS1_VIEW, header: RUNNING });
    await run(3 * DETAIL_POLL_MS);
    expect(reads()).toBe(1);
  });

  it("sends one reread at a time and checks again after it", async () => {
    // WHY: overlapping reads could land out of order; a trigger during one still counts.
    const second = held();
    serveDetails(CONTRACT_DETAIL_GATE_PASS1, second.promise, CONTRACT_DETAIL_GATE_PASS2);
    const { rerender, result } = renderDetail();
    await run();
    rerender({ stream: { view: PASS2_VIEW, header: RUNNING } });
    await run();
    expect(reads()).toBe(2);
    rerender({ stream: { view: PASS2_VIEW, header: { ...RUNNING } } });
    await run(5_000);
    expect(reads()).toBe(2);
    second.release(CONTRACT_DETAIL_GATE_PASS1);
    await run();
    expect(reads()).toBe(3);
    expect(result.current.data).toEqual(CONTRACT_DETAIL_GATE_PASS2);
    rerender({ stream: { view: PASS2_VIEW, header: { ...RUNNING } } });
    await run(5_000);
    expect(reads()).toBe(3);
  });

  it("never rereads a detail that matches the view", async () => {
    // WHY: triggers only lead to a read when the detail is actually behind.
    const { rerender } = renderDetail();
    await run();
    rerender({ stream: { view: PASS1_VIEW, header: RUNNING } });
    await run(5_000);
    const slotMoved = patched(PASS1_VIEW, [{ op: "replace", path: "/slots/0/drift", value: true }]);
    rerender({ stream: { view: slotMoved, header: { ...RUNNING } } });
    await run(5_000);
    expect(reads()).toBe(1);
  });
});

describe("useDetailFailure", () => {
  it("keeps a never-loaded detail's failure while it is read again, until a read succeeds", async () => {
    // WHY: a reread clears the query's error while it runs; the page's failed state and its
    // Retry must not blink away with it.
    const second = held();
    let answer: () => Promise<Response> = async () => jsonResponse(500, {});
    authenticatedFetch.mockImplementation(() => answer());
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    const { result } = renderHook(
      () => {
        const detail = useRunDetail(RUN_ID, NOTHING);
        return { detail, failure: useDetailFailure(detail) };
      },
      { wrapper },
    );
    await run(5_000);
    // A server error is read once more, then shown.
    expect(reads()).toBe(2);
    const failed = result.current.failure;
    expect(failed).toBeInstanceOf(ApiError);
    answer = async () => jsonResponse(200, await second.promise);
    await act(async () => {
      void result.current.detail.refetch();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(reads()).toBe(3);
    expect(result.current.detail.error).toBeNull();
    expect(result.current.failure).toBe(failed);
    second.release(CONTRACT_DETAIL_GATE_PASS1);
    await run();
    expect(result.current.detail.data?.run_id).toBe(RUN_ID);
    expect(result.current.failure).toBeNull();
  });
});

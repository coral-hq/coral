import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import { ConversationRegistry } from "@/store/conversationRegistry";
import { resetStreamSlotManager, setStreamSlotManagerForTest } from "@/store/streamSlots";

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

import { runOutcomeQueryKey, runQueryKey, runViewQueryKey } from "../api/runsApi";
import {
  countingSlots,
  FakeRunServer,
  jsonResponse,
  sseResponse,
  liveThrough,
  testBody,
  wireText,
  type CountingSlots,
} from "../fixtures/runStreamServer";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_FINAL_DETAIL,
  CONTRACT_LIVE,
  CONTRACT_RESUME_AFTER,
  CONTRACT_RESUMED,
} from "../fixtures/runViewContract";
import { coralScope } from "../shared/viewerScope";
import {
  HIDDEN_RELEASE_MS,
  LIMITED_RETRY_MS,
  SLOT_RETRIES,
  SLOT_RETRY_MS,
  type RunStreamState,
} from "./runStream";
import { evictBackgroundChat, useRunStream } from "./useRunStream";

const RUN_ID = CONTRACT_FINAL_DETAIL.run_id;
const SCOPE = coralScope("alice", "/");
const VIEW_KEY = runViewQueryKey(SCOPE, RUN_ID);

let server: FakeRunServer;
let slots: CountingSlots;

function providers(client: QueryClient, strict = false) {
  return ({ children }: { children: ReactNode }) => {
    const tree = (
      <QueryClientProvider client={client}>
        <MemoryRouter>{children}</MemoryRouter>
      </QueryClientProvider>
    );
    return strict ? <StrictMode>{tree}</StrictMode> : tree;
  };
}

function renderStream(
  options: { client?: QueryClient; onDone?: () => void; strict?: boolean } = {},
) {
  const client = options.client ?? new QueryClient();
  const wrapper = providers(client, options.strict);
  const rendered = renderHook(() => useRunStream(RUN_ID, { onDone: options.onDone }), {
    wrapper,
  });
  return { client, ...rendered };
}

/** Let fake time pass inside React's act, so queries and effects settle with it. */
const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));

beforeEach(() => {
  vi.useFakeTimers();
  server = new FakeRunServer((url) =>
    url === `/v1/coral/runs/${RUN_ID}`
      ? jsonResponse(200, CONTRACT_DETAIL_GATE_PASS1)
      : jsonResponse(404, {}),
  );
  authenticatedFetch.mockImplementation(server.fetch);
  slots = countingSlots();
  setStreamSlotManagerForTest(slots.manager);
});

afterEach(() => {
  cleanup();
  expect(slots.maxHeld()).toBeLessThanOrEqual(1);
  expect(slots.held()).toBe(0);
  resetStreamSlotManager();
  authenticatedFetch.mockReset();
  viewer.id = "alice";
  vi.useRealTimers();
});

describe("useRunStream", () => {
  it("waits for the viewer, then files every state under the run's view key", async () => {
    viewer.id = null;
    const { client, result, rerender } = renderStream();
    await run(1_000);
    expect(server.requests).toHaveLength(0);
    expect(result.current.status).toBe("connecting");

    viewer.id = "alice";
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    rerender();
    await run();
    expect(server.lastEventIds()).toEqual([null]);
    expect(result.current.status).toBe("done");
    expect(client.getQueryData(VIEW_KEY)).toBe(result.current);
  });

  it("resumes a remount from the cached view with Last-Event-ID", async () => {
    const client = new QueryClient();
    const seed: RunStreamState = {
      view: CONTRACT_DETAIL_GATE_PASS1.view,
      viewError: null,
      header: null,
      seq: CONTRACT_RESUME_AFTER,
      status: "live",
    };
    client.setQueryData(VIEW_KEY, seed);
    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    const { result } = renderStream({ client });
    expect(result.current.view).toBe(seed.view);
    await run();
    expect(server.lastEventIds()).toEqual([String(CONTRACT_RESUME_AFTER)]);
    expect(result.current.status).toBe("done");
  });

  it("opens no stream for a run whose cached view already saw [DONE]", async () => {
    const client = new QueryClient();
    const finished: RunStreamState = {
      view: CONTRACT_FINAL_DETAIL.view,
      viewError: null,
      header: null,
      seq: CONTRACT_FINAL_DETAIL.head_seq,
      status: "done",
    };
    client.setQueryData(VIEW_KEY, finished);
    const onDone = vi.fn();
    const { result } = renderStream({ client, onDone });
    await run(1_000);
    expect(server.requests).toHaveLength(0);
    expect(result.current).toBe(finished);
    expect(onDone).not.toHaveBeenCalled();
  });

  it("on [DONE], invalidates the run's detail and outcome and tells its caller once", async () => {
    const client = new QueryClient();
    const detailKey = runQueryKey(SCOPE, RUN_ID);
    const outcomeKey = runOutcomeQueryKey(SCOPE, RUN_ID);
    client.setQueryData(detailKey, CONTRACT_DETAIL_GATE_PASS1);
    client.setQueryData(outcomeKey, { run_id: RUN_ID });
    const onDone = vi.fn();
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    renderStream({ client, onDone });
    await run();
    expect(client.getQueryState(detailKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(outcomeKey)?.isInvalidated).toBe(true);
    expect(onDone).toHaveBeenCalledTimes(1);
  });

  it("aborts its stream and gives its slot back on unmount", async () => {
    const body = testBody();
    server.reply(sseResponse(body.stream));
    const { unmount } = renderStream();
    await run();
    body.send(wireText(CONTRACT_LIVE.slice(0, 2)));
    await run();
    expect(slots.held()).toBe(1);
    unmount();
    await run();
    expect(body.cancelled()).toBe(true);
    expect(slots.held()).toBe(0);
  });

  it("follows a new run id: the old stream stops and the new run starts from its own key", async () => {
    const otherRun = "b".repeat(32);
    const client = new QueryClient();
    const first = testBody();
    server.reply(sseResponse(first.stream));
    const { result, rerender } = renderHook(({ runId }) => useRunStream(runId), {
      wrapper: providers(client),
      initialProps: { runId: RUN_ID },
    });
    await run();
    first.send(wireText(liveThrough(CONTRACT_RESUME_AFTER)));
    await run();
    expect(result.current.seq).toBe(CONTRACT_RESUME_AFTER);

    const second = testBody();
    server.reply(sseResponse(second.stream));
    rerender({ runId: otherRun });
    expect(result.current).toMatchObject({ view: null, seq: null });
    await run();
    expect(first.cancelled()).toBe(true);
    expect(server.streamRequests().map((request) => request.url)).toEqual([
      `/v1/coral/runs/${RUN_ID}/stream`,
      `/v1/coral/runs/${otherRun}/stream`,
    ]);
    expect(server.lastEventIds()).toEqual([null, null]);
    expect(client.getQueryData<RunStreamState>(VIEW_KEY)?.seq).toBe(CONTRACT_RESUME_AFTER);
    expect(slots.held()).toBe(1);
  });

  it("gives its slot back after 30 s with the document hidden, and resumes once visible", async () => {
    let hidden = false;
    Object.defineProperty(document, "hidden", { configurable: true, get: () => hidden });
    const setHidden = (next: boolean) => {
      hidden = next;
      document.dispatchEvent(new Event("visibilitychange"));
    };
    try {
      const body = testBody();
      server.reply(sseResponse(body.stream));
      const { result } = renderStream();
      await run();
      body.send(wireText(liveThrough(CONTRACT_RESUME_AFTER)));
      await run();
      setHidden(true);
      // One past the release, so the cache's notification lands inside the advance.
      await run(HIDDEN_RELEASE_MS + 1);
      expect(result.current.status).toBe("paused_hidden");
      expect(slots.held()).toBe(0);
      expect(body.cancelled()).toBe(true);

      server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
      setHidden(false);
      await run();
      expect(server.lastEventIds()).toEqual([null, String(CONTRACT_RESUME_AFTER)]);
      expect(result.current.status).toBe("done");
    } finally {
      Reflect.deleteProperty(document, "hidden");
    }
  });

  it("opens one stream under StrictMode's double effect", async () => {
    server.reply(sseResponse(testBody().stream));
    renderStream({ strict: true });
    await run(1_000);
    expect(server.streamRequests()).toHaveLength(1);
    expect(slots.held()).toBe(1);
    cleanup();
  });

  it("keeps a view's own __proto__ member as data in the cache", async () => {
    const snapshot = JSON.parse(CONTRACT_LIVE[0]!.data) as Record<string, unknown>;
    const text = JSON.stringify({
      ...snapshot,
      view: { ...(snapshot.view as object), MARK: 1 },
    }).replace('"MARK":1', '"__proto__":{"polluted":true}');
    const body = testBody();
    server.reply(sseResponse(body.stream));
    const { client } = renderStream();
    await run();
    body.send(`event: snapshot\nid: 1\ndata: ${text}\n\n`);
    await run();
    // A second state, so the cache rebuilds from a previous one.
    body.send(wireText([CONTRACT_LIVE[1]!]));
    await run();
    const cached = client.getQueryData<RunStreamState>(VIEW_KEY)!;
    const view = cached.view as unknown as Record<string, unknown>;
    expect(cached.seq).toBe(2);
    expect(Object.hasOwn(view, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(view)).toBe(Object.prototype);
    expect(view.polluted).toBeUndefined();
  });

  it("aborts a hung detail read on unmount, and the hung read never blocks the stream's retry", async () => {
    const detailSignals: AbortSignal[] = [];
    authenticatedFetch.mockImplementation((input: unknown, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/stream")) return server.fetch(url, init);
      detailSignals.push(init!.signal!);
      return new Promise(() => {});
    });
    slots.setCapacity(0);
    const { unmount } = renderStream();
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(detailSignals).toHaveLength(1);
    slots.setCapacity(1);
    server.reply(sseResponse(testBody().stream));
    await run(LIMITED_RETRY_MS + 1_000);
    expect(server.streamRequests()).toHaveLength(1);
    unmount();
    await run();
    expect(detailSignals.length).toBeGreaterThan(1);
    expect(detailSignals.every((signal) => signal.aborted)).toBe(true);
  });

  it("keeps done in the cache when onDone throws", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      server.reply(sseResponse(wireText(CONTRACT_LIVE)));
      const { client } = renderStream({
        onDone: () => {
          throw new Error("ack failed");
        },
      });
      await run(1_000);
      expect(client.getQueryData<RunStreamState>(VIEW_KEY)?.status).toBe("done");
      expect(logged).toHaveBeenCalledTimes(1);
    } finally {
      logged.mockRestore();
    }
  });

  it("fills the detail's own key while live updates are limited", async () => {
    slots.setCapacity(0);
    const { client, result } = renderStream();
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(result.current.status).toBe("limited");
    expect(server.streamRequests()).toHaveLength(0);
    expect(client.getQueryData(runQueryKey(SCOPE, RUN_ID))).toEqual(CONTRACT_DETAIL_GATE_PASS1);
    expect(result.current.seq).toBe(CONTRACT_DETAIL_GATE_PASS1.head_seq);
  });
});

describe("evictBackgroundChat", () => {
  it("frees this tab's least recently viewed chat, never a retained one such as the open drawer's", () => {
    const registry = new ConversationRegistry();
    registry.acquire("drawer-session");
    registry.acquire("background-chat");
    registry.acquire("on-screen");
    registry.setActive("on-screen");
    const releaseDrawer = registry.retain("drawer-session");

    expect(evictBackgroundChat(registry)).toBe(true);
    expect(registry.ids()).toEqual(["drawer-session", "on-screen"]);
    expect(evictBackgroundChat(registry)).toBe(false);
    expect(registry.ids()).toEqual(["drawer-session", "on-screen"]);

    releaseDrawer();
    expect(evictBackgroundChat(registry)).toBe(true);
    expect(registry.ids()).toEqual(["on-screen"]);
  });
});

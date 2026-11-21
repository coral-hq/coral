import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import { ApiError } from "@/lib/sessionsApi";
import { ConversationRegistry } from "@/store/conversationRegistry";
import type { StreamSlot, StreamSlotManager } from "@/store/streamSlots";
import type { RunDetail, RunView } from "../api/generated/coralApi";
import {
  countingSlots,
  FakeRunServer,
  jsonResponse,
  liveThrough,
  sseResponse,
  testBody,
  wireEvent,
  wireText,
  type CountingSlots,
} from "../fixtures/runStreamServer";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_FINAL_DETAIL,
  CONTRACT_FINAL_SNAPSHOT,
  CONTRACT_LIVE,
  CONTRACT_LIVE_MARKS,
  CONTRACT_LIVE_RAW,
  CONTRACT_RESUME_AFTER,
  CONTRACT_RESUMED,
  type ContractEvent,
} from "../fixtures/runViewContract";
import {
  abortableSleep,
  HIDDEN_RELEASE_MS,
  LIMITED_POLL_MS,
  LIMITED_RETRY_MS,
  MAX_RETRY_AFTER_MS,
  SLOT_RETRIES,
  SLOT_RETRY_MS,
  startRunStream,
  type RunStreamDeps,
  type RunStreamState,
} from "./runStream";
import { MAX_SSE_EVENT_CHARS } from "./sseParser";
import { evictBackgroundChat } from "./useRunStream";

const RUN_ID = CONTRACT_FINAL_DETAIL.run_id;
const BACKOFF_MS = 100;

const dataOf = (event: ContractEvent) => JSON.parse(event.data) as Record<string, unknown>;
const FINAL_VIEW = dataOf(CONTRACT_FINAL_SNAPSHOT[0]!).view as RunView;
const LIVE_SNAPSHOT = CONTRACT_LIVE[0]!;
const liveEntry = (seq: number) => CONTRACT_LIVE.find((event) => event.id === String(seq))!;

/** A recorded entry with its fields changed, as a server holding a corrupt row might send it. */
function changedEntry(seq: number, changes: Record<string, unknown>): string {
  const data = JSON.stringify({ ...dataOf(liveEntry(seq)), ...changes });
  return wireEvent({ event: "entry", id: String(seq), data });
}

function frame(data: Record<string, unknown>): string {
  return wireEvent({ event: String(data.type), id: null, data: JSON.stringify(data) });
}

/** A 200 event stream whose body arrives one byte per chunk. */
function byteByByte(text: string): Response {
  const bytes = new TextEncoder().encode(text);
  return sseResponse(
    new ReadableStream<Uint8Array>({
      start(controller) {
        for (const byte of bytes) controller.enqueue(Uint8Array.of(byte));
        controller.close();
      },
    }),
  );
}

interface Harness {
  server: FakeRunServer;
  slots: CountingSlots;
  states: RunStreamState[];
  backoffs: number[];
  evict: Mock<() => boolean>;
  readDetail: Mock<(signal: AbortSignal) => Promise<RunDetail>>;
  setHidden: (hidden: boolean) => void;
  state: () => RunStreamState;
  stop: () => void;
}

interface HarnessOptions {
  runId?: string;
  seed?: RunStreamState | null;
  capacity?: number;
  slots?: StreamSlotManager;
  evict?: () => boolean;
  detail?: RunDetail;
  readDetail?: (signal: AbortSignal) => Promise<RunDetail>;
  onState?: (state: RunStreamState) => void;
  sleep?: RunStreamDeps["sleep"];
  hidden?: boolean;
}

let harness: Harness | null = null;

function start(options: HarnessOptions = {}): Harness {
  const server = new FakeRunServer();
  const slots = countingSlots(options.capacity ?? 3);
  const states: RunStreamState[] = [];
  const backoffs: number[] = [];
  const listeners = new Set<() => void>();
  let hidden = options.hidden ?? false;
  const evict = vi.fn(options.evict ?? (() => false));
  const readDetail = vi.fn(
    options.readDetail ??
      ((_signal: AbortSignal) => Promise.resolve(options.detail ?? CONTRACT_DETAIL_GATE_PASS1)),
  );
  const deps: RunStreamDeps = {
    fetch: server.fetch,
    slots: () => options.slots ?? slots.manager,
    evictBackgroundChat: evict,
    readDetail,
    waitBackoff: (failures, signal) => {
      backoffs.push(failures);
      return abortableSleep(BACKOFF_MS, signal);
    },
    sleep: options.sleep ?? abortableSleep,
    visibility: {
      hidden: () => hidden,
      subscribe: (onChange) => {
        listeners.add(onChange);
        return () => listeners.delete(onChange);
      },
    },
  };
  const stop = startRunStream(options.runId ?? RUN_ID, options.seed ?? null, deps, (state) => {
    states.push(state);
    options.onState?.(state);
  });
  harness = {
    server,
    slots,
    states,
    backoffs,
    evict,
    readDetail,
    setHidden: (next) => {
      hidden = next;
      for (const listener of listeners) listener();
    },
    state: () => states.at(-1)!,
    stop,
  };
  return harness;
}

/** Let fake time pass, running every timer and promise due in it. */
const run = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

/** The seqs the client took, in order: each change of its held seq. */
function takenSeqs(states: readonly RunStreamState[]): number[] {
  const seqs: number[] = [];
  let held: number | null = null;
  for (const state of states) {
    if (state.seq !== held && state.seq !== null) seqs.push(state.seq);
    held = state.seq;
  }
  return seqs;
}

const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, index) => from + index);

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  if (harness !== null) {
    harness.stop();
    // Every path holds at most one slot, and nothing stays held once stopped.
    expect(harness.slots.maxHeld()).toBeLessThanOrEqual(1);
    expect(harness.slots.held()).toBe(0);
    harness = null;
  }
  vi.useRealTimers();
});

describe("startRunStream: the recorded run", () => {
  it("connects without a cursor and follows the live recording to [DONE]", async () => {
    const { server, states, slots, state } = start();
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    await run();

    expect(server.streamRequests()).toHaveLength(1);
    const [request] = server.streamRequests();
    expect(request!.url).toBe(`/v1/coral/runs/${RUN_ID}/stream`);
    expect(request!.headers.get("Accept")).toBe("text/event-stream");
    expect(server.lastEventIds()).toEqual([null]);
    expect(takenSeqs(states)).toEqual(range(1, 15));
    expect(state().status).toBe("done");
    expect(state().view).toEqual(FINAL_VIEW);
    expect(state().header?.status).toBe("completed");
    expect(slots.held()).toBe(0);
  });

  it("holds a running header while gate 1 is open, which is what reads as Needs you", async () => {
    const { server, states } = start();
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    await run();

    const atGate = states.findLast((state) => state.seq === CONTRACT_LIVE_MARKS.gate1_open)!;
    expect(atGate.header?.status).toBe("running");
    expect(atGate.view?.open_gates).toEqual([CONTRACT_DETAIL_GATE_PASS1.gates[0]!.token]);
    const paused = states.findLast((state) => state.seq === CONTRACT_LIVE_MARKS.paused)!;
    expect(paused.header?.status).toBe("paused");
    expect(paused.view?.open_gates).toHaveLength(1);
  });

  it.each([
    ["the body ends", false],
    ["the connection breaks", true],
  ])(
    "resumes a dropped stream with Last-Event-ID, with no gap or repeat, when %s",
    async (_name, breaks) => {
      const { server, states, state } = start();
      const body = testBody();
      server.reply(sseResponse(body.stream));
      server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
      await run();
      body.send(wireText(liveThrough(CONTRACT_RESUME_AFTER)));
      await run();
      expect(state().seq).toBe(CONTRACT_RESUME_AFTER);
      if (breaks) body.fail();
      else body.close();
      await run(BACKOFF_MS);

      expect(server.lastEventIds()).toEqual([null, String(CONTRACT_RESUME_AFTER)]);
      expect(takenSeqs(states)).toEqual(range(1, 15));
      expect(state().status).toBe("done");
      expect(state().view).toEqual(FINAL_VIEW);
      expect(state().header?.status).toBe("completed");
    },
  );

  it("follows the live recording when every byte arrives in its own chunk", async () => {
    const { server, states, state } = start();
    server.reply(byteByByte(CONTRACT_LIVE_RAW));
    await run();
    expect(takenSeqs(states)).toEqual(range(1, 15));
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("decodes a multi-byte character split across chunks", async () => {
    const { server, state } = start();
    const status = "wörking ✓ 日本語 😀";
    const patch = [{ op: "replace", path: "/slots/0/status", value: status }];
    server.reply(
      byteByByte(`${wireText(liveThrough(2))}${changedEntry(3, { patch })}data: [DONE]\n\n`),
    );
    await run();
    expect(state()).toMatchObject({ status: "done", seq: 3 });
    expect(state().view?.slots[0]?.status).toBe(status);
  });

  it("reads each frame by its JSON type, with no event line", async () => {
    const { server, state } = start();
    server.reply(sseResponse(wireText(CONTRACT_LIVE.map((event) => ({ ...event, event: null })))));
    await run();
    expect(state()).toMatchObject({ status: "done", seq: 15, view: FINAL_VIEW });
  });

  it("ignores an entry it already holds", async () => {
    const { server, states, state } = start();
    server.reply(sseResponse(wireText(liveThrough(CONTRACT_RESUME_AFTER))));
    const [header, ...rest] = CONTRACT_RESUMED;
    const repeated = [header!, liveEntry(5), liveEntry(6), ...rest];
    server.reply(sseResponse(wireText(repeated)));
    await run(BACKOFF_MS);

    expect(takenSeqs(states)).toEqual(range(1, 15));
    expect(state().view).toEqual(FINAL_VIEW);
  });

  it("takes a seeded view and resumes after its seq", async () => {
    const seed: RunStreamState = {
      view: CONTRACT_DETAIL_GATE_PASS1.view,
      viewError: null,
      header: null,
      seq: CONTRACT_RESUME_AFTER,
      status: "limited",
    };
    const { server, states, state } = start({ seed });
    // The cached view stays on screen while the stream resumes.
    expect(states[0]).toEqual({ ...seed, status: "live" });
    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    await run();

    expect(server.lastEventIds()).toEqual([String(CONTRACT_RESUME_AFTER)]);
    expect(state().view).toEqual(FINAL_VIEW);
  });

  it("does nothing for a seed that already saw [DONE]", async () => {
    const seed: RunStreamState = {
      view: FINAL_VIEW,
      viewError: null,
      header: null,
      seq: 15,
      status: "done",
    };
    const { server, states, slots } = start({ seed });
    await run(LIMITED_RETRY_MS);
    expect(server.requests).toHaveLength(0);
    expect(slots.attempts()).toBe(0);
    expect(states).toEqual([]);
  });
});

describe("startRunStream: frames", () => {
  const afterSnapshot = wireText([LIVE_SNAPSHOT, liveEntry(2)]);

  it.each([
    ["a seq gap", wireEvent(liveEntry(4))],
    [
      "a patch that does not apply",
      changedEntry(3, { patch: [{ op: "remove", path: "/nope", value: null }] }),
    ],
    ["malformed JSON", "event: entry\nid: 3\ndata: {nope\n\n"],
    ["a frame that fails its check", changedEntry(3, { seq: "3" })],
    ["an oversized event", `data: ${"x".repeat(MAX_SSE_EVENT_CHARS)}\n\n`],
  ])("reconnects without Last-Event-ID after %s, keeping the view", async (_name, fault) => {
    const { server, states, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(afterSnapshot);
    await run();
    const shown = state().view;
    expect(state().seq).toBe(2);

    body.send(fault);
    await run();
    expect(body.cancelled()).toBe(true);
    expect(state()).toMatchObject({ seq: null, status: "reconnecting" });
    expect(state().view).toBe(shown);

    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(BACKOFF_MS);
    expect(server.lastEventIds()).toEqual([null, null]);
    expect(states.some((item) => item.seq === 3)).toBe(false);
    expect(state()).toMatchObject({ seq: 15, status: "done", view: FINAL_VIEW });
  });

  it("reconnects fresh after an entry whose value nests too deep to copy", async () => {
    const { server, states, state } = start();
    const depth = 1_000_000;
    const entry = changedEntry(3, { patch: [{ op: "add", path: "/x", value: "DEEP" }] }).replace(
      '"DEEP"',
      `${"[".repeat(depth)}${"]".repeat(depth)}`,
    );
    server.reply(sseResponse(afterSnapshot + entry));
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(BACKOFF_MS);
    expect(server.lastEventIds()).toEqual([null, null]);
    expect(states.some((item) => item.status === "failed")).toBe(false);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("ignores a run frame older than the header it holds, and takes an equal one", async () => {
    const { server, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(wireEvent(LIVE_SNAPSHOT));
    await run();
    const header = state().header!;
    const older = { ...header, type: "run", status: "paused", version: header.version - 1 };
    body.send(frame(older));
    await run();
    expect(state().header).toEqual(header);

    body.send(frame({ ...older, version: header.version }));
    await run();
    expect(state().header).toEqual({ ...header, status: "paused" });
  });

  it("keeps the view through a resync, and the snapshot after it replaces the view", async () => {
    const { server, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(afterSnapshot);
    await run();
    const shown = state().view;

    body.send(frame({ type: "resync", reason: "row_unreadable" }));
    await run();
    expect(state().view).toBe(shown);
    expect(state().seq).toBeNull();

    body.send(wireEvent(CONTRACT_FINAL_SNAPSHOT[0]!));
    await run();
    expect(state()).toMatchObject({ seq: 15, view: FINAL_VIEW, status: "live" });
  });

  it.each(["cursor_invalid", "cursor_unknown", "replay_too_long", "row_unreadable"])(
    "takes the snapshot after a %s resync that opens a resumed stream",
    async (reason) => {
      const { server, state } = start();
      server.reply(sseResponse(wireText(liveThrough(CONTRACT_RESUME_AFTER))));
      server.reply(
        sseResponse(frame({ type: "resync", reason }) + wireText(CONTRACT_FINAL_SNAPSHOT)),
      );
      await run(BACKOFF_MS);
      expect(server.lastEventIds()).toEqual([null, String(CONTRACT_RESUME_AFTER)]);
      expect(state()).toMatchObject({ status: "done", seq: 15, view: FINAL_VIEW });
    },
  );

  it("reconnects without Last-Event-ID when a stream ends between a resync and its snapshot", async () => {
    const { server, state } = start();
    server.reply(sseResponse(afterSnapshot + frame({ type: "resync", reason: "row_unreadable" })));
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(BACKOFF_MS);
    expect(server.lastEventIds()).toEqual([null, null]);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("changes nothing on a heartbeat or a frame type it does not know", async () => {
    const { server, states } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(afterSnapshot);
    await run();
    const seen = states.length;
    body.send(frame({ type: "heartbeat" }) + frame({ type: "future", x: 1 }));
    await run();
    expect(states).toHaveLength(seen);
  });

  it("advances an unloadable run's seq without applying its patches", async () => {
    const { server, state } = start();
    const snapshot = {
      ...dataOf(LIVE_SNAPSHOT),
      view: null,
      view_error: "engine.load_failed",
    };
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(
      wireEvent({ event: "snapshot", id: "1", data: JSON.stringify(snapshot) }) +
        changedEntry(2, { patch: [{ op: "remove", path: "/nope" }] }) +
        wireEvent(liveEntry(3)),
    );
    await run();
    expect(state()).toMatchObject({
      view: null,
      viewError: "engine.load_failed",
      seq: 3,
      status: "live",
    });
    expect(server.streamRequests()).toHaveLength(1);
  });

  it("stops at a [DONE] in the middle of a chunk and takes nothing after it", async () => {
    const { server, states, slots, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(`${afterSnapshot}data: [DONE]\n\n${wireEvent(liveEntry(3))}`);
    await run(LIMITED_RETRY_MS);
    expect(takenSeqs(states)).toEqual([1, 2]);
    expect(state().status).toBe("done");
    expect(body.cancelled()).toBe(true);
    expect(slots.held()).toBe(0);
    expect(server.streamRequests()).toHaveLength(1);
  });

  it("stops at [DONE] and gives its slot back", async () => {
    const { server, slots, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(afterSnapshot);
    await run();
    expect(slots.held()).toBe(1);
    body.send("data: [DONE]\n\n");
    await run(LIMITED_RETRY_MS);
    expect(state().status).toBe("done");
    expect(slots.held()).toBe(0);
    expect(body.cancelled()).toBe(true);
    expect(server.streamRequests()).toHaveLength(1);
  });
});

describe("startRunStream: reconnects", () => {
  it("reconnects at once after a stream that ends with frames, as every stream does at 5 minutes", async () => {
    const { server, backoffs } = start();
    server.reply(sseResponse(wireEvent(LIVE_SNAPSHOT)));
    server.reply(sseResponse(wireText([liveEntry(2)])));
    server.reply(sseResponse(testBody().stream));
    await run(2 * BACKOFF_MS);
    expect(server.lastEventIds()).toEqual([null, "1", "2"]);
    expect(backoffs).toEqual([1, 1]);
  });

  it("backs off an empty 200 instead of reconnecting at once", async () => {
    const { server, backoffs, state } = start();
    for (let reply = 0; reply < 3; reply += 1) server.reply(sseResponse(""));
    server.reply(sseResponse(testBody().stream));
    await run(3 * BACKOFF_MS);
    expect(server.streamRequests()).toHaveLength(4);
    expect(backoffs).toEqual([1, 2, 3]);
    expect(state().status).toBe("connecting");
  });

  it("backs off a stalled stream and resumes it with Last-Event-ID", async () => {
    const { server, backoffs, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    server.reply(sseResponse(testBody().stream));
    await run();
    body.send(wireEvent(LIVE_SNAPSHOT));
    await run(44_000);
    expect(server.streamRequests()).toHaveLength(1);
    await run(1_000 + BACKOFF_MS);
    expect(body.cancelled()).toBe(true);
    expect(backoffs).toEqual([1]);
    expect(server.lastEventIds()).toEqual([null, "1"]);
    expect(state().status).toBe("reconnecting");
  });

  it.each([
    ["a server error", jsonResponse(500, { error: "boom" })],
    ["a network error", new TypeError("Failed to fetch")],
    ["a body that is not an event stream", sseResponse("{}", "application/json")],
  ])("backs off %s and keeps its cursor", async (_name, failure) => {
    const { server, backoffs } = start({
      seed: { view: null, viewError: null, header: null, seq: 4, status: "live" },
    });
    server.reply(failure);
    server.reply(failure instanceof Response ? failure.clone() : failure);
    server.reply(sseResponse(testBody().stream));
    await run(2 * BACKOFF_MS);
    expect(backoffs).toEqual([1, 2]);
    expect(server.lastEventIds()).toEqual(["4", "4", "4"]);
  });

  it.each([
    [429, "5", 5_000],
    [503, "1", 1_000],
    [429, "3600", MAX_RETRY_AFTER_MS],
  ])("waits a %d's Retry-After of %s s, capped at 60 s", async (status, retryAfter, waitMs) => {
    const { server } = start();
    server.reply(
      jsonResponse(status, { error: { code: "stream_limit" } }, { "Retry-After": retryAfter }),
    );
    server.reply(sseResponse(testBody().stream));
    await run(waitMs - 1);
    expect(server.streamRequests()).toHaveLength(1);
    await run(1);
    expect(server.streamRequests()).toHaveLength(2);
  });

  it.each([
    ["no Retry-After, its backoff only", 429, () => null, BACKOFF_MS],
    [
      "a Retry-After date an hour away, 60 s",
      503,
      () => new Date(Date.now() + 3_600_000).toUTCString(),
      MAX_RETRY_AFTER_MS,
    ],
  ])("waits a refusal with %s", async (_name, status, retryAfter, waitMs) => {
    const { server } = start();
    const header = retryAfter();
    server.reply(jsonResponse(status, {}, header === null ? {} : { "Retry-After": header }));
    server.reply(sseResponse(testBody().stream));
    await run(waitMs - 1);
    expect(server.streamRequests()).toHaveLength(1);
    await run(1);
    expect(server.streamRequests()).toHaveLength(2);
  });

  it("keeps a stream that sends only heartbeats past the stall window", async () => {
    const { server, state } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(wireEvent(LIVE_SNAPSHOT));
    // The server's heartbeat every 15 s, for well past the 45 s stall window.
    const heartbeats = setInterval(() => body.send(frame({ type: "heartbeat" })), 15_000);
    await run(120_000);
    clearInterval(heartbeats);
    expect(server.streamRequests()).toHaveLength(1);
    expect(body.cancelled()).toBe(false);
    expect(state().status).toBe("live");
  });

  it("goes limited after three refusals, keeping its one slot, and retries it on the 30 s tick", async () => {
    const { server, slots, state, readDetail } = start();
    const refusal = () => jsonResponse(429, {}, { "Retry-After": "1" });
    for (let reply = 0; reply < 3; reply += 1) server.reply(refusal());
    await run(3 * 1_000);
    expect(state().status).toBe("limited");
    expect(slots.held()).toBe(1);
    expect(readDetail).toHaveBeenCalledTimes(1);
    expect(state()).toMatchObject({
      view: CONTRACT_DETAIL_GATE_PASS1.view,
      seq: CONTRACT_DETAIL_GATE_PASS1.head_seq,
    });

    await run(LIMITED_RETRY_MS - 1);
    expect(server.streamRequests()).toHaveLength(3);
    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    await run(1);
    expect(server.lastEventIds().at(-1)).toBe(String(CONTRACT_DETAIL_GATE_PASS1.head_seq));
    expect(slots.attempts()).toBe(1);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it.each([
    [404, "not_found"],
    [401, "failed"],
    [403, "failed"],
    [422, "failed"],
  ] as const)("stops at a %d as %s, giving its slot back", async (status, outcome) => {
    const { server, slots, state } = start();
    server.reply(jsonResponse(status, {}));
    await run(LIMITED_RETRY_MS);
    expect(state().status).toBe(outcome);
    expect(slots.held()).toBe(0);
    expect(server.streamRequests()).toHaveLength(1);
  });
});

describe("startRunStream: the connection budget", () => {
  it("frees one of this tab's background chats when no slot is free, then streams", async () => {
    const { server, slots, evict, state } = start({ capacity: 0 });
    // The evicted chat's pump frees its slot a moment later.
    evict.mockImplementation(() => {
      setTimeout(() => slots.setCapacity(1), 300);
      return true;
    });
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    await run(2 * SLOT_RETRY_MS);
    expect(evict).toHaveBeenCalledTimes(1);
    expect(server.streamRequests()).toHaveLength(1);
    expect(state().status).toBe("done");
  });

  it("goes limited with no stream request when no slot frees, polls the detail and recovers", async () => {
    const { server, slots, evict, readDetail, state } = start({ capacity: 0 });
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(evict).toHaveBeenCalledTimes(1);
    expect(slots.attempts()).toBe(1 + SLOT_RETRIES);
    expect(server.streamRequests()).toHaveLength(0);
    expect(state()).toMatchObject({
      status: "limited",
      view: CONTRACT_DETAIL_GATE_PASS1.view,
      seq: CONTRACT_DETAIL_GATE_PASS1.head_seq,
    });
    expect(state().header).toMatchObject({
      status: CONTRACT_DETAIL_GATE_PASS1.status,
      version: CONTRACT_DETAIL_GATE_PASS1.version,
      allowed_actions: CONTRACT_DETAIL_GATE_PASS1.allowed_actions,
    });
    await run(LIMITED_POLL_MS);
    expect(readDetail).toHaveBeenCalledTimes(2);

    slots.setCapacity(1);
    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    await run(LIMITED_RETRY_MS - LIMITED_POLL_MS);
    expect(server.lastEventIds()).toEqual([String(CONTRACT_DETAIL_GATE_PASS1.head_seq)]);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
    expect(evict).toHaveBeenCalledTimes(1);
  });

  it("keeps polling while limited when a detail read fails, as offline", async () => {
    const { readDetail, state } = start({ capacity: 0 });
    readDetail.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(state()).toMatchObject({ status: "limited", view: null, seq: null });
    await run(LIMITED_POLL_MS);
    expect(readDetail).toHaveBeenCalledTimes(2);
    expect(state()).toMatchObject({
      status: "limited",
      seq: CONTRACT_DETAIL_GATE_PASS1.head_seq,
    });
  });

  it("ends as not_found when the detail it polls while limited is a 404", async () => {
    const { readDetail, server, state } = start({ capacity: 0 });
    readDetail.mockRejectedValue(new ApiError("Run not found.", 404, "not_found"));
    await run(SLOT_RETRIES * SLOT_RETRY_MS + LIMITED_RETRY_MS);
    expect(state().status).toBe("not_found");
    expect(readDetail).toHaveBeenCalledTimes(1);
    expect(server.requests).toHaveLength(0);
  });

  it("tries one eviction again on each 30 s tick while limited", async () => {
    const { evict, state } = start({ capacity: 0 });
    await run(SLOT_RETRIES * SLOT_RETRY_MS + LIMITED_RETRY_MS + SLOT_RETRIES * SLOT_RETRY_MS);
    expect(state().status).toBe("limited");
    expect(evict).toHaveBeenCalledTimes(2);
  });

  it("never evicts the open drawer's session, only a background chat", async () => {
    const registry = new ConversationRegistry();
    registry.acquire("drawer-session");
    registry.acquire("background-chat");
    const releaseDrawer = registry.retain("drawer-session");
    const { state } = start({ capacity: 0, evict: () => evictBackgroundChat(registry) });
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(registry.has("background-chat")).toBe(false);
    expect(registry.has("drawer-session")).toBe(true);

    await run(LIMITED_RETRY_MS + SLOT_RETRIES * SLOT_RETRY_MS);
    expect(state().status).toBe("limited");
    expect(registry.has("drawer-session")).toBe(true);
    releaseDrawer();
  });

  it("gives its slot back after 30 s hidden and resumes with Last-Event-ID once visible", async () => {
    const { server, slots, state, setHidden } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(wireText(liveThrough(CONTRACT_RESUME_AFTER)));
    await run();

    setHidden(true);
    await run(HIDDEN_RELEASE_MS - 1);
    expect(slots.held()).toBe(1);
    expect(state().status).toBe("live");
    await run(1);
    expect(state().status).toBe("paused_hidden");
    expect(slots.held()).toBe(0);
    expect(body.cancelled()).toBe(true);
    await run(LIMITED_RETRY_MS);
    expect(server.streamRequests()).toHaveLength(1);

    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    setHidden(false);
    await run();
    expect(server.lastEventIds()).toEqual([null, String(CONTRACT_RESUME_AFTER)]);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("keeps its stream when the page is shown again within 30 s", async () => {
    const { server, slots, state, setHidden } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(wireEvent(LIVE_SNAPSHOT));
    await run();
    setHidden(true);
    await run(HIDDEN_RELEASE_MS - 1);
    setHidden(false);
    await run(1_000);
    expect(state().status).toBe("live");
    expect(slots.held()).toBe(1);
    expect(body.cancelled()).toBe(false);
  });

  it("stops polling while hidden in limited mode", async () => {
    const { readDetail, state, setHidden } = start({ capacity: 0 });
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    setHidden(true);
    await run(HIDDEN_RELEASE_MS);
    expect(state().status).toBe("paused_hidden");
    const polls = readDetail.mock.calls.length;
    await run(4 * LIMITED_RETRY_MS);
    expect(readDetail).toHaveBeenCalledTimes(polls);
  });

  it("releases a slot granted after stop", async () => {
    let grant: (slot: StreamSlot | null) => void = () => {};
    let released = 0;
    const slots: StreamSlotManager = {
      tryAcquire: () =>
        new Promise((resolve) => {
          grant = resolve;
        }),
    };
    const { server, stop, states } = start({ slots });
    await run();
    stop();
    const seen = states.length;
    grant({
      release: () => {
        released += 1;
        return Promise.resolve();
      },
    });
    await run(LIMITED_RETRY_MS);
    expect(released).toBe(1);
    expect(server.requests).toHaveLength(0);
    expect(states).toHaveLength(seen);
  });

  it("takes no slot when stopped in the task that started it", async () => {
    const { slots, stop } = start();
    stop();
    await run(LIMITED_RETRY_MS);
    expect(slots.attempts()).toBe(0);
  });

  it("aborts its open stream and gives its slot back on stop, then reports nothing", async () => {
    const { server, slots, stop, states } = start();
    const body = testBody();
    server.reply(sseResponse(body.stream));
    await run();
    body.send(wireEvent(LIVE_SNAPSHOT));
    await run();
    stop();
    const seen = states.length;
    await run();
    expect(body.cancelled()).toBe(true);
    expect(slots.held()).toBe(0);
    body.send(wireEvent(liveEntry(2)));
    await run(LIMITED_RETRY_MS);
    expect(states).toHaveLength(seen);
  });
});

describe("startRunStream: the request target", () => {
  it.each([
    [
      "../../v1/sessions/s1?x=1#y",
      "/v1/coral/runs/..%2F..%2Fv1%2Fsessions%2Fs1%3Fx%3D1%23y/stream",
    ],
    ["https://evil.example/x", "/v1/coral/runs/https%3A%2F%2Fevil.example%2Fx/stream"],
    ["//evil.example", "/v1/coral/runs/%2F%2Fevil.example/stream"],
  ])("keeps the run id %j inside the run's own stream path", async (runId, url) => {
    const { server } = start({ runId });
    server.reply(sseResponse(testBody().stream));
    await run();
    expect(server.streamRequests().map((request) => request.url)).toEqual([url]);
  });

  it.each(["", ".", ".."])(
    "ends a run id %j that names no path as not_found, with no request",
    async (runId) => {
      const { server, slots, state } = start({ runId });
      await run(LIMITED_RETRY_MS);
      expect(state().status).toBe("not_found");
      expect(server.requests).toHaveLength(0);
      expect(slots.held()).toBe(0);
    },
  );
});

/** Run `action` after `depth` microtasks. */
function afterMicrotasks(depth: number, action: () => void): void {
  if (depth === 0) action();
  else queueMicrotask(() => afterMicrotasks(depth - 1, action));
}

describe("startRunStream: a slot grant overtaken by a stop or a hide", () => {
  /** `slots`, running `action` `depth` microtasks into each request. */
  function overtaking(slots: CountingSlots, depth: number, action: () => void): StreamSlotManager {
    return {
      tryAcquire: () => {
        afterMicrotasks(depth, action);
        return slots.manager.tryAcquire();
      },
    };
  }

  it.each(range(0, 9))("releases the slot when a stop lands %d microtasks in", async (depth) => {
    const slots = countingSlots(1);
    start({ slots: overtaking(slots, depth, () => harness!.stop()) });
    await run();
    expect(slots.attempts()).toBe(1);
    expect(slots.held()).toBe(0);
  });

  it.each(range(0, 9))("releases the slot when a hide lands %d microtasks in", async (depth) => {
    const slots = countingSlots(1);
    let hide: () => void = () => {};
    const { state, setHidden } = start({
      slots: overtaking(slots, depth, () => hide()),
      // The 30 s hidden release ends when the test says.
      sleep: (ms, signal) =>
        ms === HIDDEN_RELEASE_MS
          ? new Promise<void>((resolve) => {
              hide = resolve;
            })
          : abortableSleep(ms, signal),
    });
    setHidden(true);
    await run();
    expect(slots.attempts()).toBe(1);
    expect(state().status).toBe("paused_hidden");
    expect(slots.held()).toBe(0);
  });

  it("waits for a slot it is handing back before asking for another", async () => {
    // One origin slot, whose release lands 50 ms after it is asked for.
    let held = false;
    const slots: StreamSlotManager = {
      tryAcquire: () => {
        if (held) return Promise.resolve(null);
        held = true;
        const release = () =>
          new Promise<void>((resolve) => {
            setTimeout(() => {
              held = false;
              resolve();
            }, 50);
          });
        return Promise.resolve({ release });
      },
    };
    const first = start({ slots });
    first.server.reply(sseResponse(testBody().stream));
    await run();
    expect(first.server.streamRequests()).toHaveLength(1);
    first.stop();

    // The next run's controller, as a page switching runs starts it.
    const second = start({ slots });
    second.server.reply(sseResponse(testBody().stream));
    await run(100);
    expect(second.evict).not.toHaveBeenCalled();
    expect(second.server.streamRequests()).toHaveLength(1);
    second.stop();
    await run(100);
    expect(held).toBe(false);
  });
});

describe("startRunStream: limited mode", () => {
  it("abandons a detail read that hangs, aborting it, so polls go on and the stream recovers", async () => {
    const signals: AbortSignal[] = [];
    const { server, slots, state } = start({
      capacity: 0,
      readDetail: (signal) => {
        signals.push(signal);
        return new Promise(() => {});
      },
    });
    await run(SLOT_RETRIES * SLOT_RETRY_MS);
    expect(state().status).toBe("limited");
    expect(signals).toHaveLength(1);
    await run(LIMITED_POLL_MS);
    expect(signals).toHaveLength(2);
    expect(signals[0]!.aborted).toBe(true);

    slots.setCapacity(1);
    server.reply(sseResponse(wireText(CONTRACT_FINAL_SNAPSHOT)));
    await run(LIMITED_RETRY_MS - LIMITED_POLL_MS);
    expect(server.streamRequests()).toHaveLength(1);
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
    expect(signals.every((signal) => signal.aborted)).toBe(true);
  });

  it("stops polling once the detail says the run finished, still retrying the stream", async () => {
    const { readDetail, evict, state } = start({ capacity: 0, detail: CONTRACT_FINAL_DETAIL });
    // Limited at 1 s; stream retries at 31 s and 62 s, each with one eviction.
    await run(63_000);
    expect(state()).toMatchObject({ status: "limited", view: CONTRACT_FINAL_DETAIL.view });
    expect(state().header?.status).toBe("completed");
    expect(readDetail).toHaveBeenCalledTimes(1);
    expect(evict).toHaveBeenCalledTimes(3);
  });

  it("keeps polling when a retry is refused, and retries no sooner than its Retry-After", async () => {
    const { server, readDetail, state } = start();
    const refusal = (seconds: string) => jsonResponse(429, {}, { "Retry-After": seconds });
    for (let reply = 0; reply < 3; reply += 1) server.reply(refusal("1"));
    await run(3_000);
    expect(state().status).toBe("limited");

    server.reply(refusal("60"));
    await run(LIMITED_RETRY_MS);
    expect(server.streamRequests()).toHaveLength(4);
    expect(state().status).toBe("limited");
    const polls = readDetail.mock.calls.length;
    await run(2 * LIMITED_POLL_MS);
    expect(readDetail).toHaveBeenCalledTimes(polls + 2);

    server.reply(sseResponse(wireText(CONTRACT_RESUMED)));
    await run(MAX_RETRY_AFTER_MS - 2 * LIMITED_POLL_MS - 1);
    expect(server.streamRequests()).toHaveLength(4);
    await run(1);
    expect(server.lastEventIds().at(-1)).toBe(String(CONTRACT_DETAIL_GATE_PASS1.head_seq));
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("polls the detail, and never retries the stream, when it sends a newer protocol", async () => {
    const { server, slots, readDetail, state, setHidden } = start();
    const newer = JSON.stringify({ ...dataOf(LIVE_SNAPSHOT), protocol: 2 });
    server.reply(sseResponse(wireEvent({ event: "snapshot", id: "1", data: newer })));
    await run();
    expect(state()).toMatchObject({
      status: "outdated",
      seq: CONTRACT_DETAIL_GATE_PASS1.head_seq,
    });
    expect(slots.held()).toBe(0);
    await run(2 * LIMITED_RETRY_MS);
    expect(server.streamRequests()).toHaveLength(1);
    expect(readDetail.mock.calls.length).toBeGreaterThan(1);

    setHidden(true);
    await run(HIDDEN_RELEASE_MS);
    expect(state().status).toBe("paused_hidden");
    setHidden(false);
    await run(LIMITED_RETRY_MS);
    expect(state().status).toBe("outdated");
    expect(server.streamRequests()).toHaveLength(1);
    expect(slots.attempts()).toBe(1);
  });
});

describe("startRunStream: opening, and its listener", () => {
  it("takes no slot and evicts nothing while it opens on a hidden page", async () => {
    const { server, slots, evict, state, setHidden } = start({ hidden: true, capacity: 0 });
    await run(LIMITED_RETRY_MS);
    expect(state().status).toBe("paused_hidden");
    expect(slots.attempts()).toBe(0);
    expect(evict).not.toHaveBeenCalled();
    expect(server.requests).toHaveLength(0);

    slots.setCapacity(1);
    server.reply(sseResponse(wireText(CONTRACT_LIVE)));
    setHidden(false);
    await run();
    expect(state()).toMatchObject({ status: "done", view: FINAL_VIEW });
  });

  it("keeps following the run, and ends done, when its listener throws", async () => {
    const logged = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      const { server, states } = start({
        onState: (state) => {
          if (state.seq === 2 || state.status === "done") throw new Error("listener failed");
        },
      });
      server.reply(sseResponse(wireText(CONTRACT_LIVE)));
      await run(LIMITED_RETRY_MS);
      expect(states.at(-1)!.status).toBe("done");
      expect(states.map((state) => state.status)).not.toContain("failed");
      expect(takenSeqs(states)).toEqual(range(1, 15));
      expect(server.streamRequests()).toHaveLength(1);
      expect(logged).toHaveBeenCalledTimes(2);
    } finally {
      logged.mockRestore();
    }
  });
});

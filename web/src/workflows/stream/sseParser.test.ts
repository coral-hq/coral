import { describe, expect, it } from "vitest";
import { CONTRACT_LIVE, CONTRACT_LIVE_RAW } from "../fixtures/runViewContract";
import { MAX_SSE_EVENT_CHARS, SseOverflowError, SseParser, type SseEvent } from "./sseParser";

// The live recording as a WHATWG parser reports it: an event without an `event:` line is a
// "message" (the fixture stores the missing line as null).
const LIVE_EVENTS: SseEvent[] = CONTRACT_LIVE.map((event) => ({
  event: event.event ?? "message",
  id: event.id,
  data: event.data,
}));

function parseChunks(chunks: readonly string[]): SseEvent[] {
  const parser = new SseParser();
  return [...chunks.flatMap((chunk) => parser.push(chunk)), ...parser.end()];
}

/** Decode `bytes` split at `cuts` the way the stream client does: one streaming decoder. */
function decodeAt(bytes: Uint8Array, cuts: readonly number[]): string[] {
  const decoder = new TextDecoder();
  const bounds = [0, ...cuts, bytes.length];
  return bounds
    .slice(1)
    .map((end, index) => decoder.decode(bytes.subarray(bounds[index], end), { stream: true }));
}

describe("SseParser", () => {
  it("reads the recorded live stream into its events", () => {
    expect(parseChunks([CONTRACT_LIVE_RAW])).toEqual(LIVE_EVENTS);
  });

  it("reads the recorded live stream split at every byte offset", () => {
    const bytes = new TextEncoder().encode(CONTRACT_LIVE_RAW);
    const expected = JSON.stringify(LIVE_EVENTS);
    for (let offset = 0; offset <= bytes.length; offset += 1) {
      const events = parseChunks(decodeAt(bytes, [offset]));
      if (JSON.stringify(events) !== expected) throw new Error(`split at ${offset}`);
    }
    expect(parseChunks(decodeAt(bytes, [1_000, 1_001]))).toEqual(LIVE_EVENTS);
  });

  it("reads the recorded live stream one byte at a time", () => {
    const bytes = new TextEncoder().encode(CONTRACT_LIVE_RAW);
    const cuts = Array.from({ length: bytes.length - 1 }, (_, index) => index + 1);
    expect(parseChunks(decodeAt(bytes, cuts))).toEqual(LIVE_EVENTS);
  });

  it.each([
    ["LF", "\n"],
    ["CRLF", "\r\n"],
    ["CR", "\r"],
  ])("ends lines at %s", (_name, end) => {
    const text = `event: entry${end}id: 7${end}data: {"a":1}${end}${end}data: [DONE]${end}${end}`;
    expect(parseChunks([text])).toEqual([
      { event: "entry", id: "7", data: '{"a":1}' },
      { event: "message", id: null, data: "[DONE]" },
    ]);
  });

  it("keeps a CRLF split across two chunks as one line end", () => {
    expect(parseChunks(["data: a\r", "\ndata: b\r", "\n\r", "\n"])).toEqual([
      { event: "message", id: null, data: "a\nb" },
    ]);
  });

  it("strips a leading byte order mark only", () => {
    expect(parseChunks(["﻿data: a\n\n", "data: ﻿b\n\n"])).toEqual([
      { event: "message", id: null, data: "a" },
      { event: "message", id: null, data: "﻿b" },
    ]);
    expect(parseChunks(["", "﻿", "data: a\n\n"])).toEqual([
      { event: "message", id: null, data: "a" },
    ]);
  });

  it("joins data lines, strips one space after the colon and skips comments", () => {
    const text = ": keep-alive\ndata:one\ndata:  two\ndata\n: another\nevent:run\n\n";
    expect(parseChunks([text])).toEqual([{ event: "run", id: null, data: "one\n two\n" }]);
  });

  it("drops an event with no data line, and an empty data line is an empty event", () => {
    expect(parseChunks(["event: run\nid: 3\n\n", "data:\n\n"])).toEqual([
      { event: "message", id: null, data: "" },
    ]);
  });

  it("gives each event only its own id, and ignores an id holding NUL", () => {
    const text = "id: 4\ndata: a\n\ndata: b\n\nid: 5\u0000\ndata: c\n\nid:\ndata: d\n\n";
    expect(parseChunks([text]).map((event) => event.id)).toEqual(["4", null, null, ""]);
  });

  it("ignores retry and unknown fields", () => {
    expect(parseChunks(["retry: 10\nfoo: bar\ndata: a\n\n"])).toEqual([
      { event: "message", id: null, data: "a" },
    ]);
  });

  it("drops a trailing event that never got its blank line", () => {
    const parser = new SseParser();
    expect(parser.push("data: a\n\ndata: cut")).toEqual([
      { event: "message", id: null, data: "a" },
    ]);
    expect(parser.end()).toEqual([]);
  });

  it("takes an event of exactly the cap", () => {
    const line = `data: ${"x".repeat(MAX_SSE_EVENT_CHARS - "data: ".length)}`;
    expect(parseChunks([`${line}\n\n`])[0]!.data).toHaveLength(MAX_SSE_EVENT_CHARS - 6);
  });

  it("refuses an event past the cap, before its line has ended", () => {
    const parser = new SseParser();
    const half = "x".repeat(MAX_SSE_EVENT_CHARS / 2);
    parser.push(`data: ${half}`);
    expect(() => parser.push(half)).toThrow(SseOverflowError);
  });

  it("refuses an event whose lines add up past the cap", () => {
    const parser = new SseParser();
    const line = `data: ${"x".repeat(MAX_SSE_EVENT_CHARS / 4)}\n`;
    expect(() => parser.push(line.repeat(4))).toThrow(SseOverflowError);
  });

  it("counts the cap per event, so a long stream of small events never trips it", () => {
    const parser = new SseParser();
    const event = `data: ${"x".repeat(MAX_SSE_EVENT_CHARS / 2)}\n\n`;
    expect(parser.push(event + event + event)).toHaveLength(3);
  });
});

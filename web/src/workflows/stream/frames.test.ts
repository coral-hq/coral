import { describe, expect, it } from "vitest";
import { CONTRACT_FINAL_SNAPSHOT, CONTRACT_LIVE } from "../fixtures/runViewContract";
import { MalformedFrameError, parseStreamEvent, UnsupportedStreamError } from "./frames";
import type { SseEvent } from "./sseParser";

const message = (data: string, event = "message"): SseEvent => ({ event, id: null, data });

const SNAPSHOT = JSON.parse(CONTRACT_LIVE[0]!.data) as Record<string, unknown>;
const ENTRY = JSON.parse(CONTRACT_LIVE[1]!.data) as Record<string, unknown>;
const RUN = JSON.parse(CONTRACT_LIVE.find((event) => event.event === "run")!.data) as Record<
  string,
  unknown
>;

function withField(frame: Record<string, unknown>, key: string, value: unknown): SseEvent {
  return message(JSON.stringify({ ...frame, [key]: value }));
}

describe("parseStreamEvent", () => {
  it("reads every recorded frame as its own type", () => {
    const types = [...CONTRACT_LIVE, ...CONTRACT_FINAL_SNAPSHOT].map(
      (event) => parseStreamEvent({ ...event, event: event.event ?? "message" }).type,
    );
    expect(new Set(types)).toEqual(new Set(["snapshot", "entry", "run", "done"]));
    expect(types.filter((type) => type === "done")).toHaveLength(2);
  });

  it("reads [DONE] as the end", () => {
    expect(parseStreamEvent(message("[DONE]"))).toEqual({ type: "done" });
  });

  it("reads resync and heartbeat frames", () => {
    expect(parseStreamEvent(message('{"type":"resync","reason":"cursor_unknown"}'))).toEqual({
      type: "resync",
      reason: "cursor_unknown",
    });
    expect(parseStreamEvent(message('{"type":"heartbeat"}'))).toEqual({ type: "heartbeat" });
  });

  it("returns the parsed value itself, with members zod would drop", () => {
    const patch = [{ op: "add", path: "/x", value: "VALUE" }];
    const text = JSON.stringify({ ...ENTRY, patch }).replace('"VALUE"', '{"__proto__":1}');
    const item = parseStreamEvent(message(text));
    expect(item.type).toBe("entry");
    const value = (item as { patch: { value: object }[] }).patch[0]!.value;
    expect(Object.hasOwn(value, "__proto__")).toBe(true);
  });

  it("takes an operation without its value, as the server's applier does", () => {
    const patch = [{ op: "add", path: "/x" }];
    expect(parseStreamEvent(withField(ENTRY, "patch", patch)).type).toBe("entry");
  });

  it.each([
    ["protocol", 2],
    ["view_version", 2],
  ])("names a snapshot of a newer %s as unsupported", (key, value) => {
    expect(() => parseStreamEvent(withField(SNAPSHOT, key, value))).toThrow(UnsupportedStreamError);
  });

  it("reads an older or odd protocol as malformed, not unsupported", () => {
    for (const value of [0, "2", null]) {
      const read = () => parseStreamEvent(withField(SNAPSHOT, "protocol", value));
      expect(read).toThrow(MalformedFrameError);
      expect(read).not.toThrow(UnsupportedStreamError);
    }
  });

  it("reads a frame type it does not know as unknown", () => {
    expect(parseStreamEvent(message('{"type":"future","x":1}'))).toEqual({ type: "unknown" });
    expect(parseStreamEvent(message('{"type":"constructor"}'))).toEqual({ type: "unknown" });
  });

  it("takes a status or reason this client has no name for, so a newer server still streams", () => {
    const run = { ...(SNAPSHOT.run as Record<string, unknown>), status: "archived" };
    expect(parseStreamEvent(withField(SNAPSHOT, "run", run)).type).toBe("snapshot");
    expect(parseStreamEvent(withField(RUN, "pause_reason", "new_reason")).type).toBe("run");
  });

  it.each([
    ["malformed JSON", message("{nope")],
    ["a JSON value that is not an object", message("[1]")],
    ["a frame without a type", message('{"seq":1}')],
    ["a type only under an own __proto__ member", message('{"__proto__":{"type":"heartbeat"}}')],
    ["a snapshot with a negative seq", withField(SNAPSHOT, "seq", -1)],
    ["a snapshot of another protocol", withField(SNAPSHOT, "protocol", 2)],
    ["a snapshot with neither a view nor its error", withField(SNAPSHOT, "view", null)],
    [
      "a snapshot with both a view and its error",
      withField(SNAPSHOT, "view_error", "engine.load_failed"),
    ],
    ["a snapshot whose view lacks its slots", withField(SNAPSHOT, "view", { status: "running" })],
    ["an entry with a fractional seq", withField(ENTRY, "seq", 2.5)],
    ["an entry whose patch is not a list", withField(ENTRY, "patch", {})],
    ["an entry with an operation lacking its path", withField(ENTRY, "patch", [{ op: "add" }])],
    ["a run frame without its version", withField(RUN, "version", null)],
    ["a resync without its reason", message('{"type":"resync"}')],
  ])("refuses %s", (_name, event) => {
    expect(() => parseStreamEvent(event)).toThrow(MalformedFrameError);
  });
});

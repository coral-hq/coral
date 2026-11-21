// A server-sent events parser for the run stream (WHATWG event-stream parsing). Unlike the
// session stream's parser it keeps each event's `id:`, which is the run-log seq a reconnect
// resumes after, and it caps one event's size. `retry:` is ignored: the client owns its delays.

/** The most characters one event may hold, its lines and any line still arriving. */
export const MAX_SSE_EVENT_CHARS = 8 << 20;

/** An event grew past {@link MAX_SSE_EVENT_CHARS}. */
export class SseOverflowError extends Error {
  constructor() {
    super(`A server-sent event exceeded ${MAX_SSE_EVENT_CHARS} characters.`);
    this.name = "SseOverflowError";
  }
}

/** One event: its type ("message" without an `event:` line), its own `id:` line, its data. */
export interface SseEvent {
  event: string;
  id: string | null;
  data: string;
}

const LINE_FEED = 10;
const CARRIAGE_RETURN = 13;
const BYTE_ORDER_MARK = "﻿";

export class SseParser {
  private pending = "";
  // The previous chunk ended in CR, so a LF that starts this one ends the same line.
  private skipLineFeed = false;
  private atStart = true;
  private eventType = "";
  private eventId: string | null = null;
  private dataLines: string[] = [];
  private eventChars = 0;

  /**
   * The events completed by `chunk`.
   *
   * @throws SseOverflowError when the event being read exceeds the cap.
   */
  push(chunk: string): SseEvent[] {
    let text = chunk;
    if (this.atStart && text.length > 0) {
      this.atStart = false;
      if (text.startsWith(BYTE_ORDER_MARK)) text = text.slice(1);
    }
    let start = 0;
    if (this.skipLineFeed && text.length > 0) {
      this.skipLineFeed = false;
      if (text.charCodeAt(0) === LINE_FEED) start = 1;
    }
    const events: SseEvent[] = [];
    for (let index = start; index < text.length; index += 1) {
      const code = text.charCodeAt(index);
      if (code !== LINE_FEED && code !== CARRIAGE_RETURN) continue;
      const line = this.pending + text.slice(start, index);
      this.pending = "";
      if (code === CARRIAGE_RETURN) {
        if (index + 1 === text.length) this.skipLineFeed = true;
        else if (text.charCodeAt(index + 1) === LINE_FEED) index += 1;
      }
      start = index + 1;
      this.takeLine(line, events);
    }
    this.pending += text.slice(start);
    if (this.eventChars + this.pending.length > MAX_SSE_EVENT_CHARS) throw new SseOverflowError();
    return events;
  }

  /** The stream ended: an event that never got its blank line is dropped. */
  end(): SseEvent[] {
    this.pending = "";
    this.resetEvent();
    return [];
  }

  private takeLine(line: string, events: SseEvent[]): void {
    if (line === "") {
      if (this.dataLines.length > 0) {
        events.push({
          event: this.eventType === "" ? "message" : this.eventType,
          id: this.eventId,
          data: this.dataLines.join("\n"),
        });
      }
      this.resetEvent();
      return;
    }
    this.eventChars += line.length;
    if (this.eventChars > MAX_SSE_EVENT_CHARS) throw new SseOverflowError();
    if (line.startsWith(":")) return;
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.eventType = value;
    else if (field === "data") this.dataLines.push(value);
    else if (field === "id" && !value.includes("\u0000")) this.eventId = value;
  }

  private resetEvent(): void {
    this.eventType = "";
    this.eventId = null;
    this.dataLines = [];
    this.eventChars = 0;
  }
}

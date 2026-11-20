import type { StreamSlot, StreamSlotManager } from "@/store/streamSlots";
import { CONTRACT_LIVE, type ContractEvent } from "./runViewContract";

// Test-side pieces for serving the recorded run stream to the web's stream client: the
// events as the server writes them, response bodies a test feeds, a fake
// `authenticatedFetch` and a slot manager that counts what it hands out.

/** One recorded event as the server writes it (`format_sse`). */
export function wireEvent(event: ContractEvent): string {
  const eventLine = event.event === null ? "" : `event: ${event.event}\n`;
  const idLine = event.id === null ? "" : `id: ${event.id}\n`;
  return `${eventLine}${idLine}data: ${event.data}\n\n`;
}

/** Recorded events as one response body. */
export function wireText(events: readonly ContractEvent[]): string {
  return events.map(wireEvent).join("");
}

/** The live recording up to and including the entry with `seq`. */
export function liveThrough(seq: number): ContractEvent[] {
  const end = CONTRACT_LIVE.findIndex((event) => event.id === String(seq));
  if (end < 0) throw new Error(`the live recording has no event ${seq}`);
  return CONTRACT_LIVE.slice(0, end + 1);
}

/** A response body the test writes to, ends or breaks. */
export interface TestBody {
  stream: ReadableStream<Uint8Array>;
  send: (text: string) => void;
  close: () => void;
  fail: (error?: unknown) => void;
  /** Whether the client cancelled the body. */
  cancelled: () => boolean;
}

export function testBody(): TestBody {
  const encoder = new TextEncoder();
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  let cancelled = false;
  const stream = new ReadableStream<Uint8Array>({
    start(started) {
      controller = started;
    },
    cancel() {
      cancelled = true;
    },
  });
  // A body the client cancelled takes nothing more, as a closed connection would.
  const open = () => (cancelled ? null : controller);
  return {
    stream,
    send: (text) => open()?.enqueue(encoder.encode(text)),
    close: () => open()?.close(),
    fail: (error = new TypeError("network error")) => open()?.error(error),
    cancelled: () => cancelled,
  };
}

/** A 200 event stream with `body`. */
export function sseResponse(
  body: string | ReadableStream<Uint8Array>,
  contentType = "text/event-stream; charset=utf-8",
): Response {
  return new Response(body, { status: 200, headers: { "Content-Type": contentType } });
}

/** A JSON response, as the server's refusals and reads send it. */
export function jsonResponse(
  status: number,
  body: unknown,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

/** One request the client sent. */
export interface SentRequest {
  url: string;
  headers: Headers;
}

/**
 * A fake `authenticatedFetch` for the run stream. Each stream request waits for the next
 * reply the test queues, and rejects when its signal aborts; any other path is answered by
 * `other`.
 */
export class FakeRunServer {
  readonly requests: SentRequest[] = [];
  private readonly replies: (Response | Error)[] = [];
  private readonly waiting: ((reply: Response | Error) => void)[] = [];
  private readonly other: (url: string) => Response;

  constructor(other: (url: string) => Response = () => jsonResponse(404, {})) {
    this.other = other;
  }

  /** Queue the answer to the next stream request; an error rejects it, as a network failure does. */
  reply(reply: Response | Error): void {
    this.replies.push(reply);
    this.drain();
  }

  /** The stream requests sent so far. */
  streamRequests(): SentRequest[] {
    return this.requests.filter((request) => isStreamUrl(request.url));
  }

  /** The `Last-Event-ID` of each stream request, `null` where none was sent. */
  lastEventIds(): (string | null)[] {
    return this.streamRequests().map((request) => request.headers.get("Last-Event-ID"));
  }

  readonly fetch = (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = input instanceof Request ? input.url : String(input);
    this.requests.push({ url, headers: new Headers(init?.headers) });
    if (!isStreamUrl(url)) return Promise.resolve(this.other(url));
    const signal = init?.signal ?? null;
    return new Promise((resolve, reject) => {
      const abort = (): void => reject(new DOMException("The request was aborted.", "AbortError"));
      if (signal?.aborted) {
        abort();
        return;
      }
      signal?.addEventListener("abort", abort, { once: true });
      this.waiting.push((reply) => {
        signal?.removeEventListener("abort", abort);
        if (reply instanceof Error) reject(reply);
        else resolve(reply);
      });
      this.drain();
    });
  };

  private drain(): void {
    while (this.waiting.length > 0 && this.replies.length > 0) {
      this.waiting.shift()!(this.replies.shift()!);
    }
  }
}

function isStreamUrl(url: string): boolean {
  return new URL(url, "http://localhost").pathname.endsWith("/stream");
}

/** A slot manager over `capacity` origin slots that records what it hands out. */
export interface CountingSlots {
  manager: StreamSlotManager;
  /** Slots held now. */
  held: () => number;
  /** The most slots held at once. */
  maxHeld: () => number;
  /** `tryAcquire` calls so far. */
  attempts: () => number;
  setCapacity: (capacity: number) => void;
}

export function countingSlots(initialCapacity = 3): CountingSlots {
  let capacity = initialCapacity;
  let held = 0;
  let maxHeld = 0;
  let attempts = 0;
  const grant = (): StreamSlot => {
    held += 1;
    maxHeld = Math.max(maxHeld, held);
    let released = false;
    return {
      release: () => {
        if (!released) {
          released = true;
          held -= 1;
        }
        return Promise.resolve();
      },
    };
  };
  return {
    manager: {
      tryAcquire: () => {
        attempts += 1;
        return Promise.resolve(held < capacity ? grant() : null);
      },
    },
    held: () => held,
    maxHeld: () => maxHeld,
    attempts: () => attempts,
    setCapacity: (next) => {
      capacity = next;
    },
  };
}

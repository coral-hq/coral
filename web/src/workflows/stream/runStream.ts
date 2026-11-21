import type { authenticatedFetch } from "@/lib/identity";
import { parseRetryAfterMs } from "@/lib/sessionsApi";
import { withStallGuard } from "@/lib/sse";
import type { StreamSlot, StreamSlotManager } from "@/store/streamSlots";
import type {
  EntryFrame,
  RunDetail,
  RunHeader,
  RunView,
  SnapshotFrame,
} from "../api/generated/coralApi";
import { isRunNotFound, MAX_RETRY_AFTER_MS, runStreamUrl } from "../api/runsApi";
import { isFinishedRunStatus } from "../shared/runStatus";
import { parseStreamEvent, UnsupportedStreamError, type StreamItem } from "./frames";
import { SseParser, type SseEvent } from "./sseParser";
import { applyViewPatch, type JsonObject } from "./viewPatch";

// The run stream controller (contract K8, client side). It holds one run's view, header and
// seq, follows the stream with `Last-Event-ID`, reconnects fresh when a frame cannot be
// taken, and keeps within the origin's stream budget: at most one slot, freed from this
// tab's background chats when none is free, given back while the page is hidden. When no
// stream can be had it polls the run's detail ("Live updates limited") and recovers. One
// controller follows one run for one caller: each holds its own slot.

export type RunStreamStatus =
  | "connecting"
  | "live"
  | "reconnecting"
  | "limited"
  // The server streams a newer protocol: the detail is polled and the stream never retried.
  | "outdated"
  | "paused_hidden"
  | "done"
  | "not_found"
  | "failed";

export interface RunStreamState {
  view: RunView | null;
  viewError: SnapshotFrame["view_error"];
  header: RunHeader | null;
  /** The last seq held: the next connect's `Last-Event-ID`. */
  seq: number | null;
  status: RunStreamStatus;
}

export interface RunStreamDeps {
  fetch: typeof authenticatedFetch;
  slots: () => StreamSlotManager;
  /** Dispose one of this tab's background chats so its stream slot frees; whether one was. */
  evictBackgroundChat: () => boolean;
  /** The run's detail, read while live updates are limited. */
  readDetail: (signal: AbortSignal) => Promise<RunDetail>;
  /** Wait out the reconnect backoff after `failures` consecutive failures. */
  waitBackoff: (failures: number, signal: AbortSignal) => Promise<void>;
  /** Wait `ms`, or until `signal` aborts. */
  sleep: (ms: number, signal: AbortSignal) => Promise<void>;
  visibility: { hidden: () => boolean; subscribe: (onChange: () => void) => () => void };
}

/** Retries for a slot after freeing a background chat, and the wait before each. */
export const SLOT_RETRIES = 5;
export const SLOT_RETRY_MS = 200;
/** Consecutive 429 or 503 answers before live updates are limited. */
export const REFUSALS_BEFORE_LIMITED = 3;
export { MAX_RETRY_AFTER_MS };
/** While limited: how often the detail is read, and the stream tried again. */
export const LIMITED_POLL_MS = 5_000;
export const LIMITED_RETRY_MS = 30_000;
/** How long a hidden page keeps its stream before giving the slot back. */
export const HIDDEN_RELEASE_MS = 30_000;

const FINAL_REFUSALS: ReadonlySet<number> = new Set([401, 403, 422]);
const RETRIED_REFUSALS: ReadonlySet<number> = new Set([429, 503]);

const EMPTY_STATE: RunStreamState = {
  view: null,
  viewError: null,
  header: null,
  seq: null,
  status: "connecting",
};

// Slots this tab is still handing back. A request for one waits for them, so it never
// evicts a background chat for a slot that is about to free (a run switch at saturation).
let handingBack: Promise<void> = Promise.resolve();

function handBack(slot: StreamSlot): void {
  const released = slot.release().catch(() => {});
  handingBack = Promise.all([handingBack, released]).then(() => {});
}

/** What the run loop does next; `abandoned` means the phase was cut by a hide or a stop. */
type Step = "acquire" | "connect" | "limited" | "abandoned" | "end";

/**
 * Follow run `runId`'s stream, reporting each new state to `onState`.
 *
 * `seed` is a state an earlier controller reported (its view, header and seq); a seed that
 * already saw `[DONE]` is final, so nothing starts. A seed with a view restarts as `live`, so
 * the cached view stays on screen while the stream resumes.
 *
 * @returns `stop`: aborts every request and timer and releases the slot; nothing is reported
 *   after it.
 */
export function startRunStream(
  runId: string,
  seed: RunStreamState | null,
  deps: RunStreamDeps,
  onState: (state: RunStreamState) => void,
): () => void {
  if (seed?.status === "done") return () => {};
  const controller = new RunStreamController(runId, seed, deps, onState);
  controller.start();
  return () => controller.stop();
}

/** Wait `ms`; resolves early, never rejects, when `signal` aborts. */
export function abortableSleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = (): void => {
      clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    const timer = setTimeout(finish, ms);
    signal.addEventListener("abort", finish, { once: true });
    if (signal.aborted) finish();
  });
}

class RunStreamController {
  private readonly runId: string;
  private readonly deps: RunStreamDeps;
  private readonly onState: (state: RunStreamState) => void;
  private state: RunStreamState;
  private slot: StreamSlot | null = null;
  private failures = 0;
  private refusals = 0;
  private stopped = false;
  // Aborted when the page has been hidden long enough to give the slot back, or on stop.
  private phase = new AbortController();
  private parked = false;
  private hiddenTimer: AbortController | null = null;
  private wake: (() => void) | null = null;
  private unsubscribe: () => void = () => {};
  // The server streams a protocol this client cannot read.
  private outdated = false;
  // The next stream retry while limited, at least the last refusal's `Retry-After`.
  private limitedRetryMs = LIMITED_RETRY_MS;

  constructor(
    runId: string,
    seed: RunStreamState | null,
    deps: RunStreamDeps,
    onState: (state: RunStreamState) => void,
  ) {
    this.runId = runId;
    this.deps = deps;
    this.onState = onState;
    const shown = seed !== null && (seed.view !== null || seed.viewError !== null);
    this.state = seed === null ? EMPTY_STATE : { ...seed, status: shown ? "live" : "connecting" };
  }

  start(): void {
    this.report(this.state);
    this.unsubscribe = this.deps.visibility.subscribe(() => this.onVisibility());
    // A page opened hidden takes no slot, and evicts no chat, until it is shown.
    if (this.deps.visibility.hidden()) this.park();
    this.run().catch(() => {
      if (!this.stopped) this.finish("failed");
    });
  }

  stop(): void {
    if (this.stopped) return;
    this.teardown();
    this.releaseSlot();
  }

  private async run(): Promise<void> {
    // Start on a later microtask, so a controller stopped in the task that started it (React
    // StrictMode's double effect) never takes a slot.
    await Promise.resolve();
    let step: Step = "acquire";
    /* eslint-disable no-await-in-loop -- each step decides the next */
    while (!this.stopped) {
      if (this.phase.signal.aborted) {
        await this.untilShown();
        if (this.stopped) return;
        this.phase = new AbortController();
        if (!this.outdated) this.update({ status: this.retryStatus() });
        step = this.outdated ? "limited" : "acquire";
      }
      step = await this.runStep(step, this.phase.signal);
      if (step === "end") return;
    }
    /* eslint-enable no-await-in-loop */
  }

  private async runStep(step: Step, signal: AbortSignal): Promise<Step> {
    if (step === "connect") return this.connect(signal);
    if (step === "limited") return this.limited(signal);
    // `acquire`, and an abandoned step whose phase is somehow still open.
    const held = await this.acquire(signal);
    if (signal.aborted) return "abandoned";
    return held ? "connect" : "limited";
  }

  /** Take a slot: one free, else free a background chat and retry briefly. */
  private async acquire(signal: AbortSignal): Promise<boolean> {
    if (this.slot !== null) return true;
    await handingBack;
    let granted = signal.aborted ? null : await this.trySlot();
    if (granted === null && !signal.aborted) {
      this.deps.evictBackgroundChat();
      /* eslint-disable no-await-in-loop -- each retry waits for the evicted stream to close */
      for (let retry = 0; granted === null && retry < SLOT_RETRIES; retry += 1) {
        await this.deps.sleep(SLOT_RETRY_MS, signal);
        if (signal.aborted) break;
        granted = await this.trySlot();
      }
      /* eslint-enable no-await-in-loop */
    }
    // Checked in the microtask that stores the slot: a stop or a hide before it finds no slot
    // to release, so a slot granted after either is handed back here.
    if (signal.aborted) {
      if (granted !== null) handBack(granted);
      return false;
    }
    this.slot = granted;
    return granted !== null;
  }

  private async trySlot(): Promise<StreamSlot | null> {
    try {
      return await this.deps.slots().tryAcquire();
    } catch {
      return null;
    }
  }

  private async connect(signal: AbortSignal): Promise<Step> {
    let url: string;
    try {
      url = runStreamUrl(this.runId);
    } catch {
      return this.finish("not_found");
    }
    const headers: Record<string, string> = { Accept: "text/event-stream" };
    if (this.state.seq !== null) headers["Last-Event-ID"] = String(this.state.seq);
    let response: Response;
    try {
      response = await this.deps.fetch(url, { headers, signal });
    } catch {
      return signal.aborted ? "abandoned" : this.afterFailure(signal);
    }
    if (
      !signal.aborted &&
      response.status === 200 &&
      response.body !== null &&
      isEventStream(response)
    ) {
      this.refusals = 0;
      return this.read(response.body, signal);
    }
    discardBody(response);
    if (signal.aborted) return "abandoned";
    if (response.status === 404) return this.finish("not_found");
    if (FINAL_REFUSALS.has(response.status)) return this.finish("failed");
    if (RETRIED_REFUSALS.has(response.status)) return this.afterRefusal(response, signal);
    return this.afterFailure(signal);
  }

  private async read(body: ReadableStream<Uint8Array>, signal: AbortSignal): Promise<Step> {
    let stalled = false;
    const reader = withStallGuard(body, {
      onStall: () => {
        stalled = true;
      },
    }).getReader();
    const cancel = (): void => {
      reader.cancel().catch(() => {});
    };
    signal.addEventListener("abort", cancel, { once: true });
    const decoder = new TextDecoder();
    const parser = new SseParser();
    let frames = 0;
    try {
      /* eslint-disable no-await-in-loop -- a body is read one chunk at a time */
      for (;;) {
        let chunk: ReadableStreamReadResult<Uint8Array>;
        try {
          chunk = await reader.read();
        } catch {
          return signal.aborted ? "abandoned" : this.afterFailure(signal);
        }
        if (signal.aborted) return "abandoned";
        if (chunk.done) break;
        let taken: Taken;
        try {
          taken = this.takeEvents(parser.push(decoder.decode(chunk.value, { stream: true })));
        } catch (error) {
          // An oversized event, malformed data or a patch that does not apply: start over
          // from a snapshot. A protocol this client cannot read will not improve on retry.
          taken = {
            frames: 0,
            end: error instanceof UnsupportedStreamError ? "outdated" : "fresh",
          };
        }
        frames += taken.frames;
        if (taken.end !== null) {
          cancel();
          if (taken.end === "done") return this.finish("done");
          if (taken.end === "fresh") return this.fresh(signal);
          this.outdated = true;
          this.releaseSlot();
          return "limited";
        }
      }
      /* eslint-enable no-await-in-loop */
    } finally {
      signal.removeEventListener("abort", cancel);
    }
    if (stalled || frames === 0) return this.afterFailure(signal);
    // Every stream ends within five minutes; one that sent frames resumes at once.
    this.failures = 0;
    await this.deps.waitBackoff(1, signal);
    return signal.aborted ? "abandoned" : "connect";
  }

  private takeEvents(events: readonly SseEvent[]): Taken {
    let frames = 0;
    for (const event of events) {
      const item = parseStreamEvent(event);
      if (item.type === "done") return { frames, end: "done" };
      if (item.type === "snapshot" || item.type === "entry" || item.type === "run") frames += 1;
      if (!this.take(item)) return { frames, end: "fresh" };
    }
    return { frames, end: null };
  }

  /** Apply one frame; `false` when only a fresh snapshot can continue. */
  private take(item: StreamItem): boolean {
    switch (item.type) {
      case "snapshot":
        this.failures = 0;
        this.refusals = 0;
        this.update({
          view: item.view,
          viewError: item.view_error,
          header: item.run,
          seq: item.seq,
          status: "live",
        });
        return true;
      case "entry":
        return this.takeEntry(item);
      case "run":
        // A replay's opening header leads its rows; only an older header is stale.
        if (this.state.header !== null && item.version < this.state.header.version) return true;
        this.update({ header: headerOf(item), status: "live" });
        return true;
      case "resync":
        // The snapshot that follows replaces the view; it stays on screen until then.
        this.update({ seq: null });
        return true;
      default:
        return true;
    }
  }

  private takeEntry(entry: EntryFrame): boolean {
    const held = this.state.seq;
    if (held !== null && entry.seq <= held) return true;
    if (held === null || entry.seq > held + 1) return false;
    if (this.state.viewError !== null) {
      // A run that cannot be loaded has no view to patch; its seq still moves.
      this.update({ seq: entry.seq, status: "live" });
      return true;
    }
    if (this.state.view === null) return false;
    const view = applyViewPatch(this.state.view as unknown as JsonObject, entry.patch);
    this.update({ view: view as unknown as RunView, seq: entry.seq, status: "live" });
    return true;
  }

  /** Drop the cursor (the view stays on screen) and reconnect for a snapshot. */
  private async fresh(signal: AbortSignal): Promise<Step> {
    this.failures += 1;
    this.update({ seq: null, status: this.retryStatus() });
    await this.deps.waitBackoff(this.failures, signal);
    return signal.aborted ? "abandoned" : "connect";
  }

  private async afterFailure(signal: AbortSignal): Promise<Step> {
    this.failures += 1;
    this.update({ status: this.retryStatus() });
    await this.deps.waitBackoff(this.failures, signal);
    return signal.aborted ? "abandoned" : "connect";
  }

  /** A 429 or 503: wait at least its `Retry-After` (capped), keeping the slot. */
  private async afterRefusal(response: Response, signal: AbortSignal): Promise<Step> {
    const retryAfter = Math.min(
      parseRetryAfterMs(response.headers.get("Retry-After")) ?? 0,
      MAX_RETRY_AFTER_MS,
    );
    if (this.state.status === "limited") {
      // A retry from limited mode: keep polling, and retry no sooner than the server asked.
      this.refusals += 1;
      this.limitedRetryMs = Math.max(LIMITED_RETRY_MS, retryAfter);
      return "limited";
    }
    this.update({ status: this.retryStatus() });
    await Promise.all([
      this.deps.sleep(retryAfter, signal),
      this.deps.waitBackoff(Math.max(1, this.failures), signal),
    ]);
    if (signal.aborted) return "abandoned";
    this.refusals += 1;
    return this.refusals >= REFUSALS_BEFORE_LIMITED ? "limited" : "connect";
  }

  /**
   * Poll the detail every 5 s, until it reports the run finished; try the stream again every
   * 30 s (or after the last refusal's `Retry-After`), unless its protocol is outdated.
   */
  private async limited(signal: AbortSignal): Promise<Step> {
    this.update({ status: this.outdated ? "outdated" : "limited" });
    let retryMs = this.limitedRetryMs;
    this.limitedRetryMs = LIMITED_RETRY_MS;
    let sinceRetry = 0;
    /* eslint-disable no-await-in-loop -- one poll, then one wait */
    for (;;) {
      // Each read gets one tick: a read that hangs is abandoned, never waited on.
      const tick = linkedAbort(signal);
      const poll = this.headerFinished() ? null : this.pollDetail(tick.signal);
      await this.deps.sleep(LIMITED_POLL_MS, signal);
      tick.abort();
      if ((await poll) === "end") return "end";
      if (signal.aborted) return "abandoned";
      sinceRetry += LIMITED_POLL_MS;
      if (!this.outdated && sinceRetry >= retryMs) {
        sinceRetry = 0;
        retryMs = LIMITED_RETRY_MS;
        // Holding a slot (after refusals) reconnects on it; else one more eviction.
        if (await this.acquire(signal)) return "connect";
        if (signal.aborted) return "abandoned";
      }
    }
    /* eslint-enable no-await-in-loop */
  }

  private async pollDetail(signal: AbortSignal): Promise<"polled" | "end"> {
    let detail: RunDetail | null;
    try {
      detail = await untilAborted(this.deps.readDetail(signal), signal);
    } catch (error) {
      if (!signal.aborted && isRunNotFound(error)) {
        return this.finish("not_found");
      }
      return "polled";
    }
    if (detail === null || signal.aborted) return "polled";
    // Never step back behind what the stream already delivered.
    if (this.state.seq === null || detail.head_seq >= this.state.seq) {
      this.update({
        view: detail.view,
        viewError: detail.load_error,
        header: headerOf(detail),
        seq: detail.head_seq,
      });
    }
    return "polled";
  }

  private onVisibility(): void {
    if (this.stopped) return;
    if (this.deps.visibility.hidden()) {
      if (this.parked || this.hiddenTimer !== null) return;
      const timer = new AbortController();
      this.hiddenTimer = timer;
      void this.deps.sleep(HIDDEN_RELEASE_MS, timer.signal).then(() => {
        if (timer.signal.aborted) return;
        this.hiddenTimer = null;
        if (this.deps.visibility.hidden()) this.park();
      });
      return;
    }
    this.hiddenTimer?.abort();
    this.hiddenTimer = null;
    if (this.parked) {
      this.parked = false;
      this.wakeUp();
    }
  }

  /** Hidden long enough: end the current phase and give the slot back until shown. */
  private park(): void {
    if (this.stopped || this.parked) return;
    this.parked = true;
    this.phase.abort();
    this.releaseSlot();
    this.update({ status: "paused_hidden" });
  }

  private untilShown(): Promise<void> {
    if (!this.parked || this.stopped) return Promise.resolve();
    return new Promise((resolve) => {
      this.wake = resolve;
    });
  }

  private wakeUp(): void {
    const wake = this.wake;
    this.wake = null;
    wake?.();
  }

  /** End for good; torn down before reporting, so a throwing listener cannot undo it. */
  private finish(status: "done" | "not_found" | "failed"): "end" {
    this.releaseSlot();
    this.teardown();
    this.state = { ...this.state, status };
    this.report(this.state);
    return "end";
  }

  private teardown(): void {
    this.stopped = true;
    this.phase.abort();
    this.hiddenTimer?.abort();
    this.hiddenTimer = null;
    this.unsubscribe();
    this.wakeUp();
  }

  private releaseSlot(): void {
    const slot = this.slot;
    this.slot = null;
    if (slot !== null) handBack(slot);
  }

  private headerFinished(): boolean {
    return isFinishedRunStatus(this.state.header?.status);
  }

  private retryStatus(): RunStreamStatus {
    return this.state.view !== null || this.state.viewError !== null
      ? "reconnecting"
      : "connecting";
  }

  private update(changes: Partial<RunStreamState>): void {
    const next = { ...this.state, ...changes };
    if (sameState(next, this.state)) return;
    this.state = next;
    if (!this.stopped) this.report(next);
  }

  private report(state: RunStreamState): void {
    try {
      this.onState(state);
    } catch (error) {
      // A listener's failure is not the stream's: keep following the run.
      console.error("A run stream listener failed.", error);
    }
  }
}

interface Taken {
  frames: number;
  end: "fresh" | "done" | "outdated" | null;
}

/** A controller that also aborts when `parent` does, and then lets go of `parent`. */
function linkedAbort(parent: AbortSignal): AbortController {
  const child = new AbortController();
  if (parent.aborted) {
    child.abort();
    return child;
  }
  const abort = (): void => child.abort();
  parent.addEventListener("abort", abort, { once: true });
  child.signal.addEventListener("abort", () => parent.removeEventListener("abort", abort), {
    once: true,
  });
  return child;
}

/** `work`'s result, or `null` once `signal` aborts first. */
function untilAborted<T>(work: Promise<T>, signal: AbortSignal): Promise<T | null> {
  return new Promise((resolve, reject) => {
    const abort = (): void => resolve(null);
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    work.then(
      (value) => {
        signal.removeEventListener("abort", abort);
        resolve(value);
      },
      (error: unknown) => {
        signal.removeEventListener("abort", abort);
        reject(error);
      },
    );
  });
}

function headerOf(source: RunHeader): RunHeader {
  return {
    status: source.status,
    pause_reason: source.pause_reason,
    version: source.version,
    finished_at: source.finished_at,
    allowed_actions: source.allowed_actions,
    load_error: source.load_error,
  };
}

function sameState(left: RunStreamState, right: RunStreamState): boolean {
  return (
    left.view === right.view &&
    left.viewError === right.viewError &&
    left.header === right.header &&
    left.seq === right.seq &&
    left.status === right.status
  );
}

function isEventStream(response: Response): boolean {
  return (response.headers.get("Content-Type") ?? "").toLowerCase().startsWith("text/event-stream");
}

/** Free the connection of a response that will not be read. */
function discardBody(response: Response): void {
  response.body?.cancel().catch(() => {});
}

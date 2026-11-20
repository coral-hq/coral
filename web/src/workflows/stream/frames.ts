import { z } from "zod";
import type {
  ActivationView,
  EntryFrame,
  HeartbeatFrame,
  JsonPatch,
  LoopPassView,
  PauseCause,
  ResyncFrame,
  RunFrame,
  RunHeader,
  RunView,
  SlotView,
  SnapshotFrame,
} from "../api/generated/coralApi";
import type { SseEvent } from "./sseParser";

// The run stream's frames (contract K8). zod only checks a frame: the value used is the raw
// `JSON.parse` output, because zod's output drops unknown and `__proto__` members and would
// diverge from the server's view. Each check's members are pinned to the generated type's,
// so a renamed field fails the type check. Coded values (statuses, reasons, actions) are
// checked as strings: a newer server's code must not push the client into a reconnect loop,
// and the copy modules name a code they do not know.

/** The data of the stream's end. */
export const DONE_DATA = "[DONE]";

/** One event of the run stream. */
export type StreamItem =
  | SnapshotFrame
  | EntryFrame
  | RunFrame
  | ResyncFrame
  | HeartbeatFrame
  | { type: "done" }
  | { type: "unknown" };

/** An event whose data is not JSON, or a known frame that fails its check. */
export class MalformedFrameError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "MalformedFrameError";
  }
}

/** A snapshot of a protocol or view version newer than this client reads. */
export class UnsupportedStreamError extends MalformedFrameError {
  constructor() {
    super("The run stream sends a protocol this page cannot read.");
    this.name = "UnsupportedStreamError";
  }
}

const PROTOCOL = 1;
const VIEW_VERSION = 1;

type Shape<T> = Record<keyof T, z.ZodType>;

const code = z.string();
const count = z.number().int().nonnegative();
const strings = z.array(z.string());

const headerShape = {
  status: code,
  pause_reason: code.nullable(),
  version: count,
  finished_at: z.number().nullable(),
  allowed_actions: strings,
  load_error: code.nullable(),
} satisfies Shape<RunHeader>;

const runViewShape = {
  activations: z.array(
    z.object({
      id: z.string(),
      outcome: code.nullable(),
      status: code,
    } satisfies Shape<ActivationView>),
  ),
  armed_timer_keys: strings,
  causes: z.array(
    z.object({ detail: z.string(), reason: code, subject: z.string() } satisfies Shape<PauseCause>),
  ),
  loop_pass_indexes: z.array(
    z.object({
      back_arrow_id: z.string(),
      item_path: strings,
      iteration_path: strings,
      pass_index: z.number().int(),
    } satisfies Shape<LoopPassView>),
  ),
  open_decisions: strings,
  open_gates: strings,
  slots: z.array(
    z.object({
      drift: z.boolean(),
      id: z.string(),
      pending_input: z.boolean(),
      status: code,
    } satisfies Shape<SlotView>),
  ),
  status: code.nullable(),
} satisfies Shape<RunView>;

const snapshotFrame = z
  .object({
    type: z.literal("snapshot"),
    protocol: z.literal(PROTOCOL),
    view_version: z.literal(VIEW_VERSION),
    seq: count,
    run_version: count,
    log_version: count,
    run: z.object(headerShape),
    view: z.object(runViewShape).nullable(),
    view_error: code.nullable(),
  } satisfies Shape<SnapshotFrame>)
  .refine((frame) => (frame.view === null) !== (frame.view_error === null), {
    message: "a snapshot has a view or its error, never both or neither",
  });

const entryFrame = z.object({
  type: z.literal("entry"),
  seq: count.min(1),
  run_version: count,
  kind: z.string(),
  actor_kind: code,
  actor: z.string().nullable(),
  node_id: z.string().nullable(),
  scope_key: z.string().nullable(),
  at_us: z.number().int(),
  rejected: code.nullable(),
  patch: z.array(
    // The server always sends `value`; its applier also takes an operation without one.
    z.object({
      op: code,
      path: z.string(),
      value: z.unknown().optional(),
    } satisfies Shape<JsonPatch>),
  ),
} satisfies Shape<EntryFrame>);

const runFrame = z.object({
  type: z.literal("run"),
  ...headerShape,
} satisfies Shape<RunFrame>);

const resyncFrame = z.object({
  type: z.literal("resync"),
  reason: code,
} satisfies Shape<ResyncFrame>);

const heartbeatFrame = z.object({ type: z.literal("heartbeat") } satisfies Shape<HeartbeatFrame>);

const FRAME_CHECKS: ReadonlyMap<string, z.ZodType> = new Map<string, z.ZodType>([
  ["snapshot", snapshotFrame],
  ["entry", entryFrame],
  ["run", runFrame],
  ["resync", resyncFrame],
  ["heartbeat", heartbeatFrame],
]);

/**
 * The frame one event carries: `{type: "done"}` for `[DONE]`, `{type: "unknown"}` for a
 * frame type this client does not know, else the checked frame as parsed.
 *
 * @throws UnsupportedStreamError for a snapshot of another protocol or view version.
 * @throws MalformedFrameError for data that is not a JSON object with a `type`, or a known
 *   frame that fails its check.
 */
export function parseStreamEvent(event: SseEvent): StreamItem {
  if (event.data === DONE_DATA) return { type: "done" };
  let data: unknown;
  try {
    data = JSON.parse(event.data);
  } catch {
    throw new MalformedFrameError("A run stream event's data is not JSON.");
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) {
    throw new MalformedFrameError("A run stream frame is a JSON object.");
  }
  const type = (data as { type?: unknown }).type;
  if (typeof type !== "string") throw new MalformedFrameError("A run stream frame names its type.");
  if (type === "snapshot") {
    const { protocol, view_version: viewVersion } = data as Record<string, unknown>;
    const newer = (value: unknown, known: number) => typeof value === "number" && value > known;
    if (newer(protocol, PROTOCOL) || newer(viewVersion, VIEW_VERSION)) {
      throw new UnsupportedStreamError();
    }
  }
  const check = FRAME_CHECKS.get(type);
  if (check === undefined) return { type: "unknown" };
  if (!check.safeParse(data).success) {
    throw new MalformedFrameError(`A run stream ${type} frame failed its check.`);
  }
  return data as StreamItem;
}

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Conversation } from "@/hooks/useConversations";
import { showNotification } from "@/lib/browserNotifications";
import * as sessionsApi from "@/lib/sessionsApi";
import type { WorkflowAlert } from "../api/types";
import {
  CONTRACT_INBOX_PAGE,
  CONTRACT_PENDING_ELICITATIONS,
  contractAnchorRow,
} from "../fixtures/workflowInboxContract";
import { parseWorkflowInboxPage } from "../inbox/workflowInboxApi";
import { useWorkflowRunNotifications } from "./useWorkflowRunNotifications";

const navigate = vi.hoisted(() => vi.fn());
const location = vi.hoisted(() => ({ pathname: "/" }));
vi.mock("@/lib/routing", () => ({
  useNavigate: () => navigate,
  useLocation: () => location,
  useRebasePath: () => (path: string) => path,
}));
vi.mock("@/lib/browserNotifications", () => ({ showNotification: vi.fn() }));
vi.mock("@/lib/sessionsApi", async (importActual) => ({
  ...(await importActual<typeof sessionsApi>()),
  getSession: vi.fn(),
}));

const ALERTS = parseWorkflowInboxPage(CONTRACT_INBOX_PAGE).data;
const PAUSE_ALERT = ALERTS[0]!;
const GATE_ALERT = ALERTS[1]!;
const GATE_PROMPT = CONTRACT_PENDING_ELICITATIONS[0]!;
const RUN_ID = GATE_ALERT.run_id;
const ANCHOR_ID = contractAnchorRow().id;
const TAG = `coral:run:${RUN_ID}`;
const GATE_BODY = "Approval needed: Approve the change?";
const STEP_BODY = "A step is waiting for your input.";
const MINUTE = 60_000;

/** Each anchor's pending prompts, as its snapshot returns them. */
let snapshots: Record<string, Record<string, unknown>[]> = {};

function anchor(count: number): Conversation {
  return contractAnchorRow({ pending_elicitations_count: count });
}

function otherRun(count: number): Conversation {
  return contractAnchorRow({
    id: "anchor_2",
    title: "Second run",
    labels: { "coral.run_id": "run_2", "coral.role": "run" },
    pending_elicitations_count: count,
  });
}

/** A step's prompt mirrored onto the anchor. */
function stepPrompt(n: number): Record<string, unknown> {
  return {
    elicitation_id: `elicit_${String(n).padStart(32, "0")}`,
    params: { message: "Allow the shell command?", target_session_id: "step_session" },
  };
}

function alert(kind: WorkflowAlert["kind"], id: string, runId = RUN_ID): WorkflowAlert {
  const base = kind === "gate" ? GATE_ALERT : PAUSE_ALERT;
  return { ...base, kind, alert_id: id.padStart(32, "0"), run_id: runId };
}

interface Props {
  enabled: boolean;
  alerts: readonly WorkflowAlert[] | undefined;
  rows: readonly Conversation[];
  scope: string;
}

/** Render the notifier; `update` re-renders and lets snapshot reads finish. */
async function watch(initial: Partial<Props> = {}) {
  let props: Props = { enabled: true, alerts: [], rows: [anchor(0)], scope: "alice", ...initial };
  const hook = renderHook(
    ({ enabled, alerts, rows, scope }: Props) =>
      useWorkflowRunNotifications(enabled, alerts, rows, scope),
    { initialProps: props },
  );
  await settle();
  const update = async (next: Partial<Props>) => {
    props = { ...props, ...next };
    hook.rerender(props);
    await settle();
  };
  return update;
}

async function settle() {
  await act(
    () =>
      new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      }),
  );
}

function shown() {
  return vi.mocked(showNotification).mock.calls.map(([params]) => params);
}

function setFocus(focused: boolean) {
  act(() => {
    window.dispatchEvent(new Event(focused ? "focus" : "blur"));
  });
}

beforeEach(() => {
  snapshots = {};
  location.pathname = "/";
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(1_767_270_000_000);
  vi.mocked(sessionsApi.getSession).mockImplementation(
    async (id: string) =>
      ({ pendingElicitations: snapshots[id] ?? [] }) as unknown as Awaited<
        ReturnType<typeof sessionsApi.getSession>
      >,
  );
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
});

describe("useWorkflowRunNotifications", () => {
  it("stays silent on the first observation", async () => {
    // WHY: what was already waiting when the app opened is not news.
    snapshots[ANCHOR_ID] = [GATE_PROMPT, stepPrompt(1)];
    await watch({ alerts: ALERTS, rows: [anchor(2)] });
    expect(showNotification).not.toHaveBeenCalled();
  });

  it("notifies a gate from its alert when its anchor is first seen with the gate pending", async () => {
    // WHY: a gate-first run's anchor can appear with its prompt already counted.
    snapshots[ANCHOR_ID] = [GATE_PROMPT];
    const update = await watch({ rows: [] });
    await update({ rows: [anchor(1)], alerts: [GATE_ALERT] });
    expect(shown()).toEqual([
      expect.objectContaining({ title: "Ship the bridge", body: GATE_BODY, tag: TAG }),
    ]);
    shown()[0]!.onClick!();
    expect(navigate).toHaveBeenCalledWith("/inbox");
  });

  it("notifies a gate once when its anchor is seen before its alert", async () => {
    // WHY: the session stream usually beats the feed; the alert still notifies, once.
    snapshots[ANCHOR_ID] = [GATE_PROMPT];
    const update = await watch({ rows: [] });
    await update({ rows: [anchor(1)] });
    expect(showNotification).not.toHaveBeenCalled();
    await update({ alerts: [GATE_ALERT] });
    await update({ alerts: [GATE_ALERT] });
    expect(shown()).toEqual([expect.objectContaining({ body: GATE_BODY })]);
  });

  it("notifies a gate once when its alert comes before its prompt", async () => {
    // WHY: the prompt raising the anchor's count is the same gate, not a new event.
    const update = await watch();
    await update({ alerts: [GATE_ALERT] });
    snapshots[ANCHOR_ID] = [GATE_PROMPT];
    await update({ rows: [anchor(1)] });
    expect(shown()).toEqual([expect.objectContaining({ body: GATE_BODY })]);
  });

  it("still notifies a step prompt that arrives after a gate was notified", async () => {
    // WHY: an earlier gate must never swallow a later prompt of the same run.
    const update = await watch({ rows: [] });
    snapshots[ANCHOR_ID] = [GATE_PROMPT];
    await update({ alerts: [GATE_ALERT] });
    await update({ rows: [anchor(1)] });
    snapshots[ANCHOR_ID] = [GATE_PROMPT, stepPrompt(1)];
    await update({ rows: [anchor(2)] });
    expect(shown()).toEqual([
      expect.objectContaining({ body: GATE_BODY }),
      expect.objectContaining({ title: "Ship the bridge", body: STEP_BODY, tag: TAG }),
    ]);
  });

  it("notifies each step prompt once, and not the prompts that were already pending", async () => {
    // WHY: a step prompt mirrored onto the anchor is the only signal a step needs the owner.
    snapshots[ANCHOR_ID] = [stepPrompt(1)];
    const update = await watch({ rows: [anchor(1)] });
    snapshots[ANCHOR_ID] = [stepPrompt(1), stepPrompt(2)];
    await update({ rows: [anchor(2)] });
    expect(showNotification).toHaveBeenCalledOnce();
    await update({ rows: [anchor(2)] });
    snapshots[ANCHOR_ID] = [stepPrompt(2)];
    await update({ rows: [anchor(1)] });
    snapshots[ANCHOR_ID] = [stepPrompt(2), GATE_PROMPT];
    await update({ rows: [anchor(2)] });
    expect(showNotification).toHaveBeenCalledOnce();
    snapshots[ANCHOR_ID] = [stepPrompt(2), GATE_PROMPT, stepPrompt(3)];
    await update({ rows: [anchor(3)] });
    expect(showNotification).toHaveBeenCalledTimes(2);
  });

  it("reads again on the next rise after a failed read", async () => {
    // WHY: one failed request must not lose the prompts behind it.
    const update = await watch();
    vi.mocked(sessionsApi.getSession).mockRejectedValueOnce(new TypeError("offline"));
    snapshots[ANCHOR_ID] = [stepPrompt(1)];
    await update({ rows: [anchor(1)] });
    expect(showNotification).not.toHaveBeenCalled();
    snapshots[ANCHOR_ID] = [stepPrompt(1), stepPrompt(2)];
    await update({ rows: [anchor(2)] });
    expect(showNotification).toHaveBeenCalledOnce();
  });

  it("ignores sessions that are not run anchors", async () => {
    // WHY: ordinary sessions keep the generic notifier.
    const plain = contractAnchorRow({ id: "plain", labels: {}, pending_elicitations_count: 0 });
    const update = await watch({ rows: [plain] });
    await update({ rows: [{ ...plain, pending_elicitations_count: 1 }] });
    expect(sessionsApi.getSession).not.toHaveBeenCalled();
    expect(showNotification).not.toHaveBeenCalled();
  });

  it("notifies a new pause alert once", async () => {
    // WHY: a paused run needs the owner even though nothing asks a question.
    const update = await watch();
    await update({ alerts: [PAUSE_ALERT] });
    await update({ alerts: [PAUSE_ALERT] });
    expect(shown()).toEqual([
      expect.objectContaining({
        title: "Ship the bridge",
        body: "Run paused: A step kept failing to finish its turn.",
        tag: TAG,
      }),
    ]);
  });

  it("limits other alerts to one per run every ten minutes, but never a gate", async () => {
    // WHY: pause churn must not flood the owner; every gate still needs an answer.
    const update = await watch({ rows: [anchor(0), otherRun(0)] });
    await update({ alerts: [alert("pause", "1")] });
    expect(showNotification).toHaveBeenCalledTimes(1);
    vi.setSystemTime(Date.now() + 5 * MINUTE);
    await update({ alerts: [alert("pause", "1"), alert("run_failed", "2")] });
    expect(showNotification).toHaveBeenCalledTimes(1);
    await update({ alerts: [alert("pause", "1"), alert("run_failed", "2"), alert("gate", "3")] });
    expect(showNotification).toHaveBeenCalledTimes(2);
    await update({ alerts: [alert("pause", "1"), alert("pause", "4", "run_2")] });
    expect(showNotification).toHaveBeenCalledTimes(3);
    vi.setSystemTime(Date.now() + 6 * MINUTE);
    await update({ alerts: [alert("pause", "5")] });
    expect(showNotification).toHaveBeenCalledTimes(4);
  });

  it("notifies one run once per update, naming the gate", async () => {
    // WHY: a gate and a pause of one run in one refresh are one notification.
    const update = await watch();
    await update({ alerts: [alert("pause", "1"), alert("gate", "2")] });
    expect(shown()).toEqual([expect.objectContaining({ body: GATE_BODY })]);
  });

  it("stays silent while the Inbox or the run's anchor is open in a focused window", async () => {
    // WHY: the owner is already looking at it.
    location.pathname = "/inbox";
    const update = await watch();
    setFocus(true);
    await update({ alerts: [alert("gate", "1")] });
    location.pathname = `/c/${ANCHOR_ID}`;
    await update({ alerts: [alert("gate", "2")] });
    expect(showNotification).not.toHaveBeenCalled();
    location.pathname = "/c/elsewhere";
    await update({ alerts: [alert("gate", "3")] });
    expect(showNotification).toHaveBeenCalledOnce();
    location.pathname = "/inbox";
    setFocus(false);
    await update({ alerts: [alert("gate", "4")] });
    expect(showNotification).toHaveBeenCalledTimes(2);
  });

  it("stays silent while the run's own page is open in a focused window", async () => {
    // WHY: the run view shows the run live, so a notification for it is noise.
    location.pathname = `/workflows/runs/${RUN_ID}`;
    const update = await watch();
    setFocus(true);
    await update({ alerts: [alert("gate", "1")] });
    expect(showNotification).not.toHaveBeenCalled();
    location.pathname = "/workflows/runs/run_2";
    await update({ alerts: [alert("gate", "2")] });
    expect(showNotification).toHaveBeenCalledOnce();
  });

  it("does nothing while disabled, and takes a fresh baseline when enabled", async () => {
    // WHY: without Coral nothing notifies; turning it on must not replay what was waiting.
    const update = await watch({ enabled: false });
    snapshots[ANCHOR_ID] = [stepPrompt(1)];
    await update({ alerts: [PAUSE_ALERT], rows: [anchor(1)] });
    expect(sessionsApi.getSession).not.toHaveBeenCalled();
    await update({ enabled: true });
    expect(showNotification).not.toHaveBeenCalled();
    await update({ alerts: [PAUSE_ALERT, alert("gate", "9")] });
    expect(showNotification).toHaveBeenCalledOnce();
  });

  it("waits for the feed to load before taking its baseline", async () => {
    // WHY: alerts that were open before the feed loaded are not new.
    const update = await watch({ alerts: undefined });
    await update({ alerts: [PAUSE_ALERT] });
    expect(showNotification).not.toHaveBeenCalled();
  });

  it("starts over for another viewer or server", async () => {
    // WHY: another viewer's open alerts are not news, and what one viewer saw is theirs.
    const update = await watch({ alerts: [PAUSE_ALERT] });
    await update({ scope: "bob", alerts: undefined });
    await update({ alerts: [alert("pause", "7")] });
    expect(showNotification).not.toHaveBeenCalled();
    await update({ alerts: [alert("pause", "7"), alert("gate", "8")] });
    expect(showNotification).toHaveBeenCalledOnce();
  });
});

import { act, cleanup, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));

import type { RunDetail } from "../api/generated/coralApi";
import { jsonResponse } from "../fixtures/runStreamServer";
import { CONTRACT_DETAIL_GATE_PASS1, CONTRACT_FINAL_DETAIL } from "../fixtures/runViewContract";
import { WORKFLOW_INBOX_QUERY_KEY } from "../inbox/useWorkflowInbox";
import { useAckRunAlerts } from "./useAckRunAlerts";

const RUN_ID = CONTRACT_FINAL_DETAIL.run_id;
const ACK_URL = "/v1/coral/inbox/ack";
const RUNNING = CONTRACT_DETAIL_GATE_PASS1;
const FINISHED = CONTRACT_FINAL_DETAIL;

interface Props {
  detail: RunDetail | undefined;
  doneSeen: boolean;
}

function renderAck(initial: Props, options: { strict?: boolean } = {}) {
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  const wrapper = ({ children }: { children: ReactNode }) => {
    const tree = <QueryClientProvider client={client}>{children}</QueryClientProvider>;
    return options.strict ? <StrictMode>{tree}</StrictMode> : tree;
  };
  const rendered = renderHook(
    ({ detail, doneSeen }: Props) => useAckRunAlerts(RUN_ID, detail, doneSeen),
    { initialProps: initial, wrapper },
  );
  return { ...rendered, invalidate };
}

const acks = () =>
  authenticatedFetch.mock.calls
    .filter(([url]) => url === ACK_URL)
    .map(([, init]) => JSON.parse((init as RequestInit).body as string) as unknown);

const settle = () => act(() => vi.advanceTimersByTimeAsync(0));

beforeEach(() => {
  vi.useFakeTimers();
  authenticatedFetch.mockImplementation(async (url: string) =>
    url === ACK_URL ? jsonResponse(200, { acked: 1 }) : jsonResponse(404, {}),
  );
});

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
  vi.useRealTimers();
});

describe("useAckRunAlerts", () => {
  it("marks a finished run's alerts read on open, once, then refreshes the Inbox", async () => {
    // WHY: opening a finished run is reading its run-end alert; the [DONE] that follows is not news.
    const { rerender, invalidate } = renderAck({ detail: FINISHED, doneSeen: false });
    await settle();
    expect(acks()).toEqual([{ run_id: RUN_ID }]);
    expect(invalidate).toHaveBeenCalledWith({ queryKey: WORKFLOW_INBOX_QUERY_KEY });
    rerender({ detail: FINISHED, doneSeen: true });
    rerender({ detail: { ...FINISHED }, doneSeen: true });
    await settle();
    expect(acks()).toHaveLength(1);
  });

  it("posts nothing before the detail loads, which confirms the owner", async () => {
    // WHY: a link to another user's run must not change anything on open.
    const { rerender } = renderAck({ detail: undefined, doneSeen: true });
    await settle();
    expect(acks()).toEqual([]);
    rerender({ detail: RUNNING, doneSeen: true });
    await settle();
    expect(acks()).toEqual([{ run_id: RUN_ID }]);
  });

  it("waits for a [DONE] seen while open before marking a running run's alerts read", async () => {
    // WHY: a running run has no run-end alert yet; it gets one when it ends in view.
    const { rerender } = renderAck({ detail: RUNNING, doneSeen: false });
    await settle();
    expect(acks()).toEqual([]);
    rerender({ detail: RUNNING, doneSeen: true });
    await settle();
    rerender({ detail: FINISHED, doneSeen: true });
    await settle();
    expect(acks()).toEqual([{ run_id: RUN_ID }]);
  });

  it("does not mark alerts read when a reread, not a [DONE], shows the run finished", async () => {
    // WHY: only opening a finished run, or watching it end, marks its alerts read.
    const { rerender } = renderAck({ detail: RUNNING, doneSeen: false });
    await settle();
    rerender({ detail: FINISHED, doneSeen: false });
    await settle();
    expect(acks()).toEqual([]);
  });

  it("ignores a failed post and never repeats it", async () => {
    // WHY: an unread alert is harmless, and a retry loop on open is not.
    authenticatedFetch.mockImplementation(async () => jsonResponse(500, {}));
    const { rerender, invalidate } = renderAck({ detail: FINISHED, doneSeen: false });
    await settle();
    rerender({ detail: { ...FINISHED }, doneSeen: true });
    await settle();
    expect(acks()).toHaveLength(1);
    expect(invalidate).not.toHaveBeenCalled();
  });

  it("posts once under StrictMode's double effects", async () => {
    // WHY: development's remounted effects must not mark alerts read twice.
    renderAck({ detail: FINISHED, doneSeen: false }, { strict: true });
    await settle();
    expect(acks()).toHaveLength(1);
  });
});

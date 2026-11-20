import { beforeEach, describe, expect, it, vi } from "vitest";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import { ackRunAlerts, WorkflowInboxError } from "./workflowInboxApi";

const RUN_ID = "84170e76f35c7a90d1280a24a7230fc9";

beforeEach(() => authenticatedFetch.mockReset());

describe("ackRunAlerts", () => {
  it("posts the run's id as JSON and reads how many alerts it marked read", async () => {
    // WHY: opening a run marks its low-priority alerts read in one request.
    authenticatedFetch.mockResolvedValue(new Response(JSON.stringify({ acked: 2 })));
    expect(await ackRunAlerts(RUN_ID)).toEqual({ acked: 2 });
    const [url, init] = authenticatedFetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/v1/coral/inbox/ack");
    expect(init.method).toBe("POST");
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({ run_id: RUN_ID });
  });

  it.each([404, 422, 500])("throws a WorkflowInboxError on a %i", async (status) => {
    // WHY: the caller ignores a failed mark-read, and a server without the Inbox answers 404.
    authenticatedFetch.mockResolvedValue(new Response(null, { status }));
    await expect(ackRunAlerts(RUN_ID)).rejects.toEqual(
      expect.objectContaining({ name: "WorkflowInboxError", status }),
    );
    await expect(ackRunAlerts(RUN_ID)).rejects.toBeInstanceOf(WorkflowInboxError);
  });
});

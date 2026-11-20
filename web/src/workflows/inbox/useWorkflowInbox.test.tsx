import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import type * as identityModule from "@/lib/identity";
import type { WorkflowAlert } from "../api/types";
import { CONTRACT_INBOX_PAGE } from "../fixtures/workflowInboxContract";
import { parseWorkflowInboxPage } from "./workflowInboxApi";
import { useWorkflowInbox } from "./useWorkflowInbox";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
const viewer = vi.hoisted(() => ({ id: "alice" as string | null }));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => viewer.id,
  useIdentityReady: () => true,
}));

const ALERTS = parseWorkflowInboxPage(CONTRACT_INBOX_PAGE).data;
const PAUSE_ALERT = ALERTS[0]!;
const GATE_ALERT = ALERTS[1]!;

function alert(index: number): WorkflowAlert {
  return {
    ...PAUSE_ALERT,
    alert_id: index.toString(16).padStart(32, "0"),
    created_at: 1_000 - index,
  };
}

function json(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), { status });
}

/** Answer feed pages by cursor and acks by alert id. */
function serve(
  pages: Record<string, unknown>,
  ack: (alertId: string) => Response | Promise<Response> = () => json(204),
) {
  authenticatedFetch.mockImplementation(async (input: string) => {
    const url = new URL(input, "http://local");
    const acked = /^\/v1\/coral\/inbox\/([^/]+)\/ack$/.exec(url.pathname);
    if (acked) return ack(decodeURIComponent(acked[1]!));
    const page = pages[url.searchParams.get("after") ?? ""];
    return page instanceof Response ? page : json(200, page);
  });
}

function feedRequests(): string[] {
  return authenticatedFetch.mock.calls
    .map(([input]) => String(input))
    .filter((input) => input.startsWith("/v1/coral/inbox?"));
}

function renderInbox(enabled = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  );
  return { client, ...renderHook(() => useWorkflowInbox(enabled), { wrapper }) };
}

beforeEach(() => {
  serve({ "": CONTRACT_INBOX_PAGE });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  authenticatedFetch.mockReset();
  viewer.id = "alice";
});

describe("useWorkflowInbox", () => {
  it("loads nothing while Coral is off", () => {
    // WHY: without Coral the app makes no workflow requests at all.
    const { result } = renderInbox(false);
    expect(authenticatedFetch).not.toHaveBeenCalled();
    expect(result.current).toMatchObject({
      alerts: [],
      loaded: false,
      isLoading: false,
      isError: false,
    });
  });

  it("loads nothing until the viewer is known", async () => {
    // WHY: a feed loaded before identity resolves would be filed under no viewer.
    viewer.id = null;
    const { result } = renderInbox();
    await act(async () => {});
    expect(authenticatedFetch).not.toHaveBeenCalled();
    expect(result.current.loaded).toBe(false);
  });

  it("files the feed under the scope it has always used", async () => {
    // WHY: the run keys share this string, and a changed shape would orphan cached feeds.
    const { result, client } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    const scope = JSON.stringify([window.location.origin, "/", "alice"]);
    expect(result.current.scope).toBe(scope);
    expect(client.getQueryState(["coral-inbox", scope])?.status).toBe("success");
  });

  it("loads the contract's page", async () => {
    // WHY: the web reads the backend's own serialized feed unchanged.
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    // Every field of every contract item is read as the backend wrote it.
    expect(parseWorkflowInboxPage(CONTRACT_INBOX_PAGE)).toEqual(CONTRACT_INBOX_PAGE);
    expect(result.current.alerts).toEqual(ALERTS);
    expect(result.current.incomplete).toBe(false);
    expect(result.current.absent).toBe(false);
    expect(feedRequests()).toEqual(["/v1/coral/inbox?limit=100"]);
  });

  it("follows the cursor through every page, empty pages included", async () => {
    // WHY: a page can be empty and still have more after it; gates must not hide behind it.
    serve({
      "": { data: [alert(1)], next_cursor: "1:900:a" },
      "1:900:a": { data: [], next_cursor: "1:800:b" },
      "1:800:b": { data: [alert(2)], next_cursor: null },
    });
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.alerts).toEqual([alert(1), alert(2)]);
    expect(result.current.incomplete).toBe(false);
    expect(feedRequests()).toEqual([
      "/v1/coral/inbox?limit=100",
      "/v1/coral/inbox?limit=100&after=1%3A900%3Aa",
      "/v1/coral/inbox?limit=100&after=1%3A800%3Ab",
    ]);
  });

  it("keeps one copy of an alert that two pages both return", async () => {
    // WHY: alerts raised between page reads can repeat one across pages; two cards would share a key.
    serve({
      "": { data: [alert(1), alert(2)], next_cursor: "1:998:b" },
      "1:998:b": { data: [alert(2), alert(3)], next_cursor: null },
    });
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.alerts).toEqual([alert(1), alert(2), alert(3)]);
  });

  it("stops after ten pages and reports the feed incomplete", async () => {
    // WHY: the feed is bounded; the badge says when it holds more than was loaded.
    const pages: Record<string, unknown> = {};
    for (let index = 0; index < 11; index += 1) {
      pages[index === 0 ? "" : `c${index}`] = {
        data: [alert(index + 1)],
        next_cursor: index === 10 ? null : `c${index + 1}`,
      };
    }
    serve(pages);
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(feedRequests()).toHaveLength(10);
    expect(result.current.alerts).toHaveLength(10);
    expect(result.current.incomplete).toBe(true);
  });

  it("treats a 404 as no feed: no alerts, no error and no retry", async () => {
    // WHY: a server without the alert store is not an outage.
    serve({ "": json(404, { detail: "Coral inbox is not available" }) });
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current).toMatchObject({ alerts: [], absent: true, isError: false });
    expect(feedRequests()).toHaveLength(1);
  });

  it("reports a failing feed as an error after one retry", async () => {
    // WHY: the Inbox shows an error row with Retry instead of an empty feed.
    serve({ "": json(500, { detail: "boom" }) });
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(feedRequests()).toHaveLength(2);
    expect(result.current.alerts).toEqual([]);
  });

  it("drops alerts the client cannot read", async () => {
    // WHY: one malformed item must not take the whole feed down.
    serve({ "": { data: [PAUSE_ALERT, { alert_id: 5 }, null], next_cursor: null } });
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    expect(result.current.alerts).toEqual([PAUSE_ALERT]);
  });

  it("marks an alert read at once and posts an empty JSON body", async () => {
    // WHY: Mark as read is optimistic; the JSON body keeps the ack out of reach of plain forms.
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    let answer: (response: Response) => void = () => {};
    serve(
      { "": { data: [GATE_ALERT], next_cursor: null } },
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );

    act(() => result.current.ack(PAUSE_ALERT.alert_id));
    // Gone while the server has not answered yet.
    await waitFor(() => expect(result.current.alerts).toEqual([GATE_ALERT]));
    expect(authenticatedFetch).toHaveBeenCalledWith(
      `/v1/coral/inbox/${PAUSE_ALERT.alert_id}/ack`,
      expect.objectContaining({ method: "POST", body: "{}" }),
    );
    expect(feedRequests()).toHaveLength(1);
    act(() => answer(json(204)));
    const init = authenticatedFetch.mock.calls.find(([input]) =>
      String(input).endsWith("/ack"),
    )![1] as RequestInit;
    expect(new Headers(init.headers).get("Content-Type")).toBe("application/json");
    await waitFor(() => expect(feedRequests()).toHaveLength(2));
    expect(result.current.alerts).toEqual([GATE_ALERT]);
  });

  it("puts the alert back where it was when marking it read fails", async () => {
    // WHY: an alert the server still holds open must not vanish from the Inbox.
    let answer: (response: Response) => void = () => {};
    serve(
      { "": CONTRACT_INBOX_PAGE },
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));

    act(() => result.current.ack(PAUSE_ALERT.alert_id));
    await waitFor(() => expect(result.current.alerts).toEqual([GATE_ALERT]));
    act(() => answer(json(500, { detail: "boom" })));
    await waitFor(() => expect(result.current.alerts).toEqual(ALERTS));
  });

  it("keeps an alert dropped when the server no longer has it", async () => {
    // WHY: a 404 means it was already read or resolved elsewhere.
    const { result } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));
    serve({ "": { data: [GATE_ALERT], next_cursor: null } }, () =>
      json(404, { detail: "alert not found" }),
    );

    act(() => result.current.ack(PAUSE_ALERT.alert_id));
    await waitFor(() => expect(feedRequests()).toHaveLength(2));
    expect(result.current.alerts).toEqual([GATE_ALERT]);
  });

  it("keeps an alert hidden while its ack is in flight, whatever loads meanwhile", async () => {
    // WHY: a load that starts during the ack still lists the alert; it must not come back.
    let answer: (response: Response) => void = () => {};
    serve(
      { "": CONTRACT_INBOX_PAGE },
      () =>
        new Promise<Response>((resolve) => {
          answer = resolve;
        }),
    );
    const { result, client } = renderInbox();
    await waitFor(() => expect(result.current.loaded).toBe(true));

    act(() => result.current.ack(PAUSE_ALERT.alert_id));
    expect(result.current.alerts).toEqual([GATE_ALERT]);
    await act(() => client.invalidateQueries({ queryKey: ["coral-inbox"] }));
    expect(feedRequests()).toHaveLength(2);
    expect(result.current.alerts).toEqual([GATE_ALERT]);

    serve({ "": { data: [GATE_ALERT], next_cursor: null } });
    act(() => answer(json(204)));
    await waitFor(() => expect(feedRequests()).toHaveLength(3));
    expect(result.current.alerts).toEqual([GATE_ALERT]);
  });

  it("keeps reloading the feed every minute while the app is hidden", async () => {
    // WHY: pause and run-end alerts notify from the feed, and the owner is usually elsewhere.
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    onTestFinished(() => hidden.mockRestore());
    const { result } = renderInbox();
    await act(() => vi.advanceTimersByTimeAsync(1_000));
    expect(result.current.loaded).toBe(true);
    expect(feedRequests()).toHaveLength(1);

    serve({ "": { data: [PAUSE_ALERT], next_cursor: null } });
    await act(() => vi.advanceTimersByTimeAsync(58_000));
    expect(feedRequests()).toHaveLength(1);
    // The minute is up; the extra time lets the response body be read.
    await act(() => vi.advanceTimersByTimeAsync(2_000));
    expect(feedRequests()).toHaveLength(2);
    expect(result.current.alerts).toEqual([PAUSE_ALERT]);
  });
});

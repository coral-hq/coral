import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import type { Conversation } from "@/hooks/useConversations";
import { showNotification } from "@/lib/browserNotifications";
import type * as identityModule from "@/lib/identity";
import { resetInboxKindsForTests, useInboxKinds } from "@/lib/inboxKinds";
import { CoralRuntime } from "./CoralRuntime";
import { CONTRACT_INBOX_PAGE, contractAnchorRow } from "./fixtures/workflowInboxContract";

const authenticatedFetch = vi.hoisted(() => vi.fn());
const sidebar = vi.hoisted(() => ({
  identityReady: true,
  serverInboxRows: [] as Conversation[],
  serverLoadedRows: [] as Conversation[],
}));
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useSidebarData", () => ({ useSidebarData: () => sidebar }));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));
vi.mock("@/lib/browserNotifications", () => ({ showNotification: vi.fn() }));

const INFO = { enabled: true, version: "0.1.0", sub_features: {} };
const EMPTY_PAGE = { data: [], next_cursor: null };

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status });
}

/** Answer Coral info and feed requests; `info` may be a promise that never settles. */
function serve(info: Response | Promise<Response>, page: unknown = CONTRACT_INBOX_PAGE) {
  authenticatedFetch.mockImplementation(async (input: string) => {
    if (input === "/v1/coral/info") return info;
    if (input.startsWith("/v1/coral/inbox")) return json(200, page);
    throw new Error(`unexpected request ${input}`);
  });
}

function requested(prefix: string): boolean {
  return authenticatedFetch.mock.calls.some(([input]) => String(input).startsWith(prefix));
}

function KindsProbe() {
  const kinds = useInboxKinds();
  return (
    <span data-testid="kinds">
      {kinds.map((kind) => `${kind.id}:${kind.badgeCount}`).join(",")}
    </span>
  );
}

function renderRuntime({ strict = false, info }: { strict?: boolean; info?: typeof INFO } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retryDelay: 0 } } });
  if (info) client.setQueryData(["coral-info"], info);
  const runtime = () =>
    strict ? (
      <StrictMode>
        <CoralRuntime />
      </StrictMode>
    ) : (
      <CoralRuntime />
    );
  const tree = () => (
    <QueryClientProvider client={client}>
      <MemoryRouter>
        {runtime()}
        <KindsProbe />
      </MemoryRouter>
    </QueryClientProvider>
  );
  const view = render(tree());
  /** Render again, as a new session list from the sidebar would. */
  const refresh = () => view.rerender(tree());
  return { client, refresh, ...view };
}

const kinds = () => screen.getByTestId("kinds").textContent;

beforeEach(() => {
  sidebar.identityReady = true;
  sidebar.serverInboxRows = [];
  sidebar.serverLoadedRows = [];
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.clearAllMocks();
  authenticatedFetch.mockReset();
  resetInboxKindsForTests();
});

function feedRequests(): number {
  return authenticatedFetch.mock.calls.filter(([input]) =>
    String(input).startsWith("/v1/coral/inbox"),
  ).length;
}

describe("CoralRuntime", () => {
  it("renders nothing and makes no request before the viewer's identity settles", () => {
    // WHY: the login path must not probe Coral.
    sidebar.identityReady = false;
    serve(json(200, INFO));
    const { container } = render(<CoralRuntime />, {
      wrapper: ({ children }) => (
        <QueryClientProvider client={new QueryClient()}>
          <MemoryRouter>{children}</MemoryRouter>
        </QueryClientProvider>
      ),
    });
    expect(container).toBeEmptyDOMElement();
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("registers nothing and never loads the feed on a server without Coral", async () => {
    // WHY: with no Coral plugin, gate-shaped prompts stay ordinary approvals and nothing is fetched.
    serve(json(404, { detail: "Not Found" }));
    renderRuntime();
    await waitFor(() => expect(requested("/v1/coral/info")).toBe(true));
    await act(async () => {});
    expect(kinds()).toBe("");
    expect(requested("/v1/coral/inbox")).toBe(false);
  });

  it("registers nothing while Coral info is loading", async () => {
    // WHY: until Coral is confirmed, gates render as approvals, which still answer.
    serve(new Promise<Response>(() => {}));
    renderRuntime();
    await waitFor(() => expect(requested("/v1/coral/info")).toBe(true));
    expect(kinds()).toBe("");
    expect(requested("/v1/coral/inbox")).toBe(false);
  });

  it("registers nothing when Coral reports itself disabled", async () => {
    // WHY: `enabled: false` means the same as no plugin.
    serve(json(200, { ...INFO, enabled: false }));
    renderRuntime();
    await waitFor(() => expect(requested("/v1/coral/info")).toBe(true));
    await act(async () => {});
    expect(kinds()).toBe("");
    expect(requested("/v1/coral/inbox")).toBe(false);
  });

  it("registers nothing and never loads the feed when Coral info keeps failing", async () => {
    // WHY: an info outage is not Coral being on; gates stay answerable approvals.
    serve(json(500, { detail: "boom" }));
    renderRuntime();
    await waitFor(() =>
      expect(
        authenticatedFetch.mock.calls.filter(([input]) => input === "/v1/coral/info"),
      ).toHaveLength(2),
    );
    await act(async () => {});
    expect(kinds()).toBe("");
    expect(requested("/v1/coral/inbox")).toBe(false);
  });

  it("keeps the kind registered through StrictMode's mount, cleanup and mount replay", async () => {
    // WHY: the app mounts the runtime under StrictMode; the replayed cleanup must not leave it unregistered.
    // Cached Coral info gives the kind on the first commit, so the replay unregisters it once;
    // the feed stays loading, so nothing re-registers it later.
    authenticatedFetch.mockImplementation((input: string) =>
      input === "/v1/coral/info" ? Promise.resolve(json(200, INFO)) : new Promise(() => {}),
    );
    const { unmount } = renderRuntime({ strict: true, info: INFO });
    await waitFor(() => expect(requested("/v1/coral/inbox")).toBe(true));
    expect(kinds()).toBe("workflow:0");
    unmount();
    render(<KindsProbe />);
    expect(kinds()).toBe("");
  });

  it("registers the workflow kind and loads the feed when Coral is available, and removes it on unmount", async () => {
    // WHY: the kind lives exactly as long as the runtime that feeds it.
    serve(json(200, INFO));
    const { unmount } = renderRuntime();
    // The pause alert and the gate alert with no loaded anchor both reach the badge.
    await waitFor(() => expect(kinds()).toBe("workflow:2"));
    expect(requested("/v1/coral/inbox?limit=100")).toBe(true);
    unmount();
    render(<KindsProbe />);
    expect(kinds()).toBe("");
  });

  it("updates the kind in place when the feed changes", async () => {
    // WHY: replacing in place keeps one kind and never flickers the Inbox.
    serve(json(200, INFO), EMPTY_PAGE);
    const { client } = renderRuntime();
    await waitFor(() => expect(kinds()).toBe("workflow:0"));
    serve(json(200, INFO), CONTRACT_INBOX_PAGE);
    await act(() => client.invalidateQueries({ queryKey: ["coral-inbox"] }));
    await waitFor(() => expect(kinds()).toBe("workflow:2"));
  });

  it("reloads the feed when a run anchor's pending count changes", async () => {
    // WHY: a gate opening or closing shows on the anchor at once; its alert should follow.
    sidebar.serverLoadedRows = [contractAnchorRow({ pending_elicitations_count: 0 })];
    serve(json(200, INFO));
    const { refresh } = renderRuntime();
    await waitFor(() => expect(kinds()).toBe("workflow:2"));
    expect(feedRequests()).toBe(1);
    refresh();
    await act(async () => {});
    expect(feedRequests()).toBe(1);
    sidebar.serverLoadedRows = [contractAnchorRow({ pending_elicitations_count: 1 })];
    refresh();
    await waitFor(() => expect(feedRequests()).toBe(2));
  });

  it("notifies a pause that happens while the app is hidden", async () => {
    // WHY: the owner is usually elsewhere when a run pauses; the feed keeps polling.
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    onTestFinished(() => hidden.mockRestore());
    /** Let fake time pass in small steps until `done` holds (at most five seconds). */
    const advanceUntil = async (done: () => boolean) => {
      for (let step = 0; step < 50 && !done(); step += 1) {
        // oxlint-disable-next-line no-await-in-loop -- each step must land before the next check.
        await act(() => vi.advanceTimersByTimeAsync(100));
      }
    };
    serve(json(200, INFO));
    renderRuntime();
    await advanceUntil(() => kinds() === "workflow:2");
    expect(kinds()).toBe("workflow:2");

    const { data } = CONTRACT_INBOX_PAGE as { data: Record<string, unknown>[] };
    const pause = { ...data[0], alert_id: "a".repeat(32), run_id: "run_2" };
    serve(json(200, INFO), { data: [pause, ...data], next_cursor: null });
    await act(() => vi.advanceTimersByTimeAsync(59_000));
    await advanceUntil(() => kinds() === "workflow:3");
    expect(kinds()).toBe("workflow:3");
    expect(showNotification).toHaveBeenCalledOnce();
    expect(showNotification).toHaveBeenCalledWith(
      expect.objectContaining({
        body: "Run paused: A step kept failing to finish its turn.",
        tag: "coral:run:run_2",
      }),
    );
  });

  it("removes the kind when Coral stops being available", async () => {
    // WHY: a disabled Coral leaves no workflow entries behind.
    serve(json(200, INFO));
    const { client } = renderRuntime();
    await waitFor(() => expect(kinds()).toBe("workflow:2"));
    act(() => client.setQueryData(["coral-info"], { ...INFO, enabled: false }));
    await waitFor(() => expect(kinds()).toBe(""));
  });
});

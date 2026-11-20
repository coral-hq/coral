import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useScopeCache", () => import("@/test/mockScopeCache"));
import {
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, type ComponentProps } from "react";
import { MemoryRouter } from "react-router-dom";
import type * as approvalCard from "@/components/blocks/ApprovalCard";
import * as automationInboxHook from "@/hooks/useAutomationInbox";
import * as commentInboxHook from "@/hooks/useCommentInbox";
import type { Conversation } from "@/hooks/useConversations";
import * as conversationsHook from "@/hooks/useConversations";
import { SidebarDataProvider, useSidebarData } from "@/hooks/useSidebarData";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { registerInboxKind, resetInboxKindsForTests } from "@/lib/inboxKinds";
import { resetLocalElicitationResolutionsForTests } from "@/lib/localElicitationResolutions";
import * as sessionsApi from "@/lib/sessionsApi";
import { InboxPage } from "@/pages/InboxPage";
import type { WorkflowAlert } from "../api/types";
import {
  CONTRACT_INBOX_PAGE,
  CONTRACT_PENDING_ELICITATIONS,
  contractAnchorRow,
} from "../fixtures/workflowInboxContract";
import type { WorkflowInbox } from "./useWorkflowInbox";
import * as workflowEntries from "./workflowEntries";
import { parseWorkflowInboxPage } from "./workflowInboxApi";
import { useWorkflowInboxKind } from "./workflowInboxKind";

// The real workflow kind inside the real Inbox page, fed the shared contract.
// Session data is mocked at the same seams as `InboxPage.test.tsx`.

vi.mock("@/components/blocks/ApprovalCard", () => ({
  ApprovalCard: (props: ComponentProps<typeof approvalCard.ApprovalCard>) => (
    <div data-testid="approval-card">{props.message}</div>
  ),
}));
vi.mock("@/hooks/useConversations", async (importActual) => ({
  ...(await importActual<typeof conversationsHook>()),
  useConversations: vi.fn(),
}));
vi.mock("./workflowEntries", async (importActual) => {
  const actual = await importActual<typeof workflowEntries>();
  return { ...actual, badgeCount: vi.fn(actual.badgeCount) };
});
vi.mock("@/hooks/useAutomationInbox", () => ({ useAutomationInbox: vi.fn() }));
vi.mock("@/hooks/useCommentInbox", () => ({ useCommentInbox: vi.fn() }));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));
vi.mock("@/lib/sessionsApi", async (importActual) => ({
  ...(await importActual<typeof sessionsApi>()),
  getSession: vi.fn(),
  approve: vi.fn(),
  fetchSessionItemsPage: vi.fn(),
}));

const ALERTS = parseWorkflowInboxPage(CONTRACT_INBOX_PAGE).data;
const PAUSE_ALERT = ALERTS[0]!;
const GATE_ALERT = ALERTS[1]!;
const GATE_EVENT = CONTRACT_PENDING_ELICITATIONS[0]!;
const GATE_ID = "coral_gate_00000000000000000000000000000001";
// Older than the gate, so the gate card starts expanded.
const ANCHOR = contractAnchorRow({ updated_at: GATE_ALERT.created_at - 60 });

function workflowInbox(overrides: Partial<WorkflowInbox> = {}): WorkflowInbox {
  return {
    alerts: ALERTS,
    loaded: true,
    incomplete: false,
    absent: false,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ack: vi.fn(),
    scope: "test",
    ...overrides,
  };
}

/** Registers the kind the way the runtime does, from the sidebar's server rows. */
function WorkflowKindHarness({ inbox }: { inbox: WorkflowInbox }) {
  const { serverInboxRows } = useSidebarData();
  const kind = useWorkflowInboxKind(inbox, serverInboxRows, true);
  useEffect(() => (kind === null ? undefined : registerInboxKind(kind)), [kind]);
  return null;
}

function BadgeProbe() {
  const { inboxCount, inboxCountIncomplete } = useSidebarData();
  return (
    <span data-testid="badge">
      {inboxCount}
      {inboxCountIncomplete ? "+" : ""}
    </span>
  );
}

interface ServerState {
  rows?: Conversation[];
  pending?: readonly Record<string, unknown>[];
  inbox?: WorkflowInbox;
}

function renderInbox({
  rows = [ANCHOR],
  pending = CONTRACT_PENDING_ELICITATIONS,
  inbox = workflowInbox(),
}: ServerState = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const tree = (state: Required<ServerState>) => {
    vi.mocked(conversationsHook.useConversations).mockReturnValue({
      data: { pages: [{ data: state.rows }] },
      isLoading: false,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
    } as unknown as ReturnType<typeof conversationsHook.useConversations>);
    vi.mocked(sessionsApi.getSession).mockResolvedValue({
      pendingElicitations: state.pending,
    } as unknown as Awaited<ReturnType<typeof sessionsApi.getSession>>);
    return (
      <QueryClientProvider client={client}>
        <CapabilitiesProvider info={FALLBACK_SERVER_INFO}>
          <SidebarDataProvider>
            <MemoryRouter>
              <WorkflowKindHarness inbox={state.inbox} />
              <BadgeProbe />
              <InboxPage />
            </MemoryRouter>
          </SidebarDataProvider>
        </CapabilitiesProvider>
      </QueryClientProvider>
    );
  };
  const { rerender } = render(tree({ rows, pending, inbox }));
  /** Show what the session list, the anchor's snapshot and the feed return after a refetch. */
  const update = (state: Required<ServerState>) => rerender(tree(state));
  return { inbox, update };
}

beforeEach(() => {
  vi.mocked(automationInboxHook.useAutomationInbox).mockReturnValue({
    items: [],
    isLoading: false,
    isError: false,
    hasNextPage: false,
    markRead: vi.fn(),
    refetch: vi.fn(),
    fetchNextPage: vi.fn(),
  } as unknown as ReturnType<typeof automationInboxHook.useAutomationInbox>);
  vi.mocked(commentInboxHook.useCommentInbox).mockReturnValue({
    items: [],
    isLoading: false,
    failedCount: 0,
    retryFailed: vi.fn(),
  });
  vi.mocked(sessionsApi.approve).mockResolvedValue({ queued: false });
  vi.mocked(sessionsApi.fetchSessionItemsPage).mockResolvedValue({ items: [], hasMore: false });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  resetInboxKindsForTests();
  resetLocalElicitationResolutionsForTests();
  localStorage.clear();
});

describe("the workflow Inbox kind", () => {
  it("shows the contract's gate as exactly one workflow card and keeps the step prompt an approval", async () => {
    // WHY: one gate is one card, never also an approval; a step's own prompt stays an approval.
    renderInbox();
    // The step prompt arrives with the anchor's snapshot, after the feed's cards.
    expect(await screen.findByTestId("inbox-item")).toHaveTextContent("Allow the shell command?");
    expect(screen.getAllByTestId("inbox-item")).toHaveLength(1);
    expect(screen.getAllByTestId("inbox-workflow-gate")).toHaveLength(1);
    expect(screen.getAllByTestId("inbox-workflow-alert")).toHaveLength(1);
    expect(screen.getByText("1 approval · 2 workflow items")).toBeInTheDocument();
    // The anchor counts its gate and the mirrored prompt; the pause alert adds one.
    expect(screen.getByTestId("badge")).toHaveTextContent("3");
  });

  it("answers the gate through the anchor's resolve route", async () => {
    // WHY: the Inbox answers the gate's own elicitation on the run anchor.
    renderInbox();
    await screen.findByTestId("inbox-item");
    const card = screen.getByTestId("inbox-workflow-gate");
    fireEvent.click(within(card).getByRole("button", { name: "approve" }));
    await waitFor(() =>
      expect(within(card).getByRole("status")).toHaveTextContent("Answered: approve."),
    );
    expect(sessionsApi.approve).toHaveBeenCalledWith(ANCHOR.id, GATE_ID, {
      action: "accept",
      content: { decision: "approve" },
    });
  });

  it("keeps one answered card while the refetches land, then drops it", async () => {
    // WHY: the session list and the feed refresh separately; neither order may re-offer the form.
    const { update } = renderInbox();
    await screen.findByTestId("inbox-item");
    fireEvent.click(
      within(screen.getByTestId("inbox-workflow-gate")).getByRole("button", { name: "approve" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("inbox-workflow-gate")).toHaveTextContent("Answered: approve."),
    );
    const mirroredOnly = {
      rows: [
        contractAnchorRow({ pending_elicitations_count: 1, updated_at: ANCHOR.updated_at + 1 }),
      ],
      pending: [CONTRACT_PENDING_ELICITATIONS[1]!],
    };

    // The session list catches up first: the gate alert alone still holds the card.
    update({ ...mirroredOnly, inbox: workflowInbox() });
    await waitFor(() => expect(sessionsApi.getSession).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByTestId("badge")).toHaveTextContent("2"));
    const card = screen.getByTestId("inbox-workflow-gate");
    expect(screen.getAllByTestId("inbox-workflow-gate")).toHaveLength(1);
    expect(card).toHaveTextContent("Answered: approve.");
    expect(within(card).queryByRole("button", { name: "approve" })).not.toBeInTheDocument();

    // Then the feed: the gate is gone and only the step prompt and the pause remain.
    update({ ...mirroredOnly, inbox: workflowInbox({ alerts: [PAUSE_ALERT] }) });
    await waitFor(() =>
      expect(screen.queryByTestId("inbox-workflow-gate")).not.toBeInTheDocument(),
    );
    expect(screen.getAllByTestId("inbox-item")).toHaveLength(1);
    expect(screen.getAllByTestId("inbox-workflow-alert")).toHaveLength(1);
    expect(screen.getByTestId("badge")).toHaveTextContent("2");
    expect(sessionsApi.approve).toHaveBeenCalledOnce();
  });

  it("keeps one answered card when the feed refreshes before the session list", async () => {
    // WHY: a prompt-only gate is the same card, so the other refresh order shows no second form either.
    const { update } = renderInbox();
    await screen.findByTestId("inbox-item");
    fireEvent.click(
      within(screen.getByTestId("inbox-workflow-gate")).getByRole("button", { name: "reject" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("inbox-workflow-gate")).toHaveTextContent("Answered: reject."),
    );
    expect(screen.getByText("Step: Approve change")).toBeInTheDocument();
    update({
      rows: [ANCHOR],
      pending: CONTRACT_PENDING_ELICITATIONS,
      inbox: workflowInbox({ alerts: [PAUSE_ALERT] }),
    });
    // Only the alert carried the step label: its absence shows the card is now prompt-only.
    await waitFor(() => expect(screen.queryByText("Step: Approve change")).not.toBeInTheDocument());
    expect(screen.getByTestId("badge")).toHaveTextContent("3");
    expect(screen.getAllByTestId("inbox-workflow-gate")).toHaveLength(1);
    expect(screen.getByTestId("inbox-workflow-gate")).toHaveTextContent("Answered: reject.");
    expect(screen.getAllByTestId("inbox-item")).toHaveLength(1);
  });

  it("shows a gate alert whose prompt is missing as one answerable card", async () => {
    // WHY: the alert alone still answers the gate, and the badge still counts it.
    renderInbox({ rows: [contractAnchorRow({ pending_elicitations_count: 0 })], pending: [] });
    const card = await screen.findByTestId("inbox-workflow-gate");
    expect(screen.getAllByTestId("inbox-workflow-gate")).toHaveLength(1);
    expect(screen.queryByTestId("inbox-item")).not.toBeInTheDocument();
    expect(screen.getByTestId("badge")).toHaveTextContent("2");
    fireEvent.click(within(card).getByRole("button", { name: "reject" }));
    await waitFor(() =>
      expect(sessionsApi.approve).toHaveBeenCalledWith(GATE_ALERT.session_id, GATE_ID, {
        action: "accept",
        content: { decision: "reject" },
      }),
    );
  });

  it("shows a gate prompt with no alert as one card", async () => {
    // WHY: the prompt can arrive before the feed refreshes.
    renderInbox({ pending: [GATE_EVENT], inbox: workflowInbox({ alerts: [] }) });
    expect(await screen.findByTestId("inbox-workflow-gate")).toBeInTheDocument();
    expect(screen.getAllByTestId("inbox-workflow-gate")).toHaveLength(1);
    expect(screen.queryByTestId("inbox-workflow-alert")).not.toBeInTheDocument();
    expect(screen.queryByTestId("inbox-item")).not.toBeInTheDocument();
  });

  it("shows a feed error with Retry while approvals still render", async () => {
    // WHY: a feed outage must not hide the approvals the session list found.
    const { inbox } = renderInbox({ inbox: workflowInbox({ alerts: [], isError: true }) });
    expect(await screen.findByTestId("inbox-item")).toHaveTextContent("Allow the shell command?");
    const row = screen.getByRole("alert");
    expect(row).toHaveTextContent("Couldn’t load workflow alerts.");
    fireEvent.click(within(row).getByRole("button", { name: "Retry" }));
    expect(inbox.refetch).toHaveBeenCalledOnce();
  });

  it("marks an alert read from its card", async () => {
    // WHY: Mark as read acks the alert on the server through the feed.
    const { inbox } = renderInbox();
    const card = await screen.findByTestId("inbox-workflow-alert");
    fireEvent.click(within(card).getByRole("button", { name: "Run paused: Ship the bridge" }));
    fireEvent.click(within(card).getByRole("button", { name: "Mark as read" }));
    expect(inbox.ack).toHaveBeenCalledWith(PAUSE_ALERT.alert_id);
  });

  it("leaves low-priority alerts out of the badge and marks it incomplete with the feed", async () => {
    // WHY: run-end alerts are listed, not badged; a cut-off feed makes the badge a lower bound.
    const low: WorkflowAlert = {
      ...PAUSE_ALERT,
      alert_id: "e".repeat(32),
      kind: "run_completed",
      priority: "low",
    };
    renderInbox({ inbox: workflowInbox({ alerts: [...ALERTS, low], incomplete: true }) });
    expect(await screen.findAllByTestId("inbox-workflow-alert")).toHaveLength(2);
    expect(screen.getByTestId("badge")).toHaveTextContent("3+");
  });
});

describe("useWorkflowInboxKind", () => {
  const rows: Conversation[] = [];

  it("is null while disabled", () => {
    // WHY: no kind is registered unless Coral is available.
    const { result } = renderHook(() => useWorkflowInboxKind(workflowInbox(), rows, false));
    expect(result.current).toBeNull();
  });

  it("silences run sessions, summarises its entries and reports the feed's state", () => {
    // WHY: run sessions notify through the workflow notifier, once per run.
    const refetch = vi.fn();
    const { result } = renderHook(() =>
      useWorkflowInboxKind(workflowInbox({ isLoading: true, isError: true, refetch }), rows, true),
    );
    const kind = result.current!;
    expect(kind.id).toBe("workflow");
    expect(kind.silences(ANCHOR)).toBe(true);
    expect(
      kind.silences(contractAnchorRow({ labels: { "coral.run_id": "r", "coral.role": "step" } })),
    ).toBe(true);
    expect(kind.silences(contractAnchorRow({ labels: {} }))).toBe(false);
    expect(kind.summary(1)).toBe("1 workflow item");
    expect(kind.summary(3)).toBe("3 workflow items");
    expect(kind.loading).toBe(true);
    expect(kind.error?.message).toBe("Couldn’t load workflow alerts.");
    kind.error?.retry();
    expect(refetch).toHaveBeenCalledOnce();
  });

  it("keeps the same kind while nothing it shows changes", () => {
    // WHY: every new kind re-registers and re-renders the sidebar.
    const inbox = workflowInbox();
    const { result, rerender } = renderHook(
      ({ current }: { current: Conversation[] }) => useWorkflowInboxKind(inbox, current, true),
      { initialProps: { current: [ANCHOR] } },
    );
    const first = result.current;
    rerender({ current: [{ ...ANCHOR }] });
    expect(result.current).toBe(first);
    rerender({ current: [] });
    expect(result.current).not.toBe(first);
    expect(result.current?.badgeCount).toBe(2);
  });

  it("counts the badge again only when the alerts or rows change", () => {
    // WHY: the runtime re-renders on every sidebar update, with up to 1,000 alerts loaded.
    const inbox = workflowInbox();
    const shown = [ANCHOR];
    const { rerender } = renderHook(
      ({ current }: { current: Conversation[] }) => useWorkflowInboxKind(inbox, current, true),
      { initialProps: { current: shown } },
    );
    rerender({ current: shown });
    expect(workflowEntries.badgeCount).toHaveBeenCalledOnce();
    rerender({ current: [ANCHOR] });
    expect(workflowEntries.badgeCount).toHaveBeenCalledTimes(2);
  });
});

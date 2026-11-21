import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation, useNavigate, type Location } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import type * as identityModule from "@/lib/identity";

// The run page inside the real app routes, as App.test.tsx's `renderRoute` mounts it. AppShell
// is a probe that shows whether it would enter chat mode (its `conversationId` param).
const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
vi.mock("@/hooks/useViewerId", () => ({
  useViewerId: () => "alice",
  useIdentityReady: () => true,
}));
vi.mock("@/lib/analytics", () => ({
  useOmnigentPageView: vi.fn(),
  useOmnigentAnalytics: () => ({ trackClick: vi.fn() }),
}));
vi.mock("@/shell/AppShell", async () => {
  const { Outlet, useParams } = await import("@/lib/routing");
  return {
    AppShell: () => {
      const { conversationId } = useParams<{ conversationId: string }>();
      return (
        <div data-testid="app-shell" data-conversation-id={conversationId ?? ""}>
          <Outlet />
        </div>
      );
    },
  };
});
vi.mock("@/pages/ChatPage", () => ({ ChatPage: () => <div>chat page</div> }));
vi.mock("@/extensions/ExtensionProvider", () => ({
  useExtensionsLoading: () => false,
  useExtensions: () => [],
}));
const sideChatPane = vi.hoisted(() => vi.fn());
vi.mock("@/components/chat/SideChatPane", () => ({
  SideChatPane: (props: { childId: string; fullSession?: boolean; readOnly?: boolean }) => {
    sideChatPane(props);
    return <div data-testid="side-chat-pane">{props.childId}</div>;
  },
}));
vi.mock("@xyflow/react", () => import("../fixtures/xyflowDouble"));
vi.mock("@xyflow/react/dist/style.css", () => ({}));

import App from "@/App";
import type { RunHeader } from "../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../fixtures/runViewContract";
import { jsonResponse } from "../fixtures/runStreamServer";
import { NOT_IN_RUN_TEXT } from "./agents/StepDrawer";

const DETAIL = CONTRACT_DETAIL_GATE_PASS2;
const RUN_ID = DETAIL.run_id;
const RUN_PATH = `/workflows/runs/${RUN_ID}`;
const S1 = DETAIL.slots.find((slot) => slot.engine_slot_id === "implement||a4:1:0")!.session_id!;
const S2 = DETAIL.slots.find((slot) => slot.engine_slot_id === "implement||a4:2:0")!.session_id!;
const RUNNING: RunHeader = {
  status: "running",
  pause_reason: null,
  version: 9,
  finished_at: null,
  allowed_actions: ["pause", "cancel"],
  load_error: null,
};
// The stream is the page's own tests' concern; here it holds the detail's view.
vi.mock("@/workflows/stream/useRunStream", () => ({
  useRunStream: () => ({
    view: CONTRACT_DETAIL_GATE_PASS2.view,
    viewError: null,
    header: RUNNING,
    seq: CONTRACT_DETAIL_GATE_PASS2.head_seq,
    status: "live",
  }),
}));

let location: Location | null = null;
let navigate: ReturnType<typeof useNavigate> = () => {};

function RouterProbe() {
  location = useLocation();
  navigate = useNavigate();
  return null;
}

function renderRoute(path: string) {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <CapabilitiesProvider info={FALLBACK_SERVER_INFO}>
        <MemoryRouter initialEntries={[path]}>
          <RouterProbe />
          <App />
        </MemoryRouter>
      </CapabilitiesProvider>
    </QueryClientProvider>,
  );
}

const shellConversationId = () => screen.getByTestId("app-shell").dataset.conversationId;
const drawer = () => screen.findByRole("complementary", { name: /Implement|Step transcript/ });
const here = () => `${location?.pathname}${location?.search}`;

beforeEach(() => {
  sideChatPane.mockReset();
  authenticatedFetch.mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/v1/coral/info")) {
      return jsonResponse(200, { enabled: true, version: "1", sub_features: {} });
    }
    if (init?.method === "POST") return jsonResponse(200, { acked: 0 });
    if (url === `/v1/coral/runs/${RUN_ID}`) return jsonResponse(200, DETAIL);
    if (url === `/v1/coral/runs/${RUN_ID}/graph`) return jsonResponse(200, CONTRACT_GRAPH);
    return jsonResponse(404, {});
  });
});

afterEach(() => {
  cleanup();
  authenticatedFetch.mockReset();
  location = null;
});

describe("the run page's step drawer", () => {
  it("opens a step's transcript from ?agent=&node= and keeps AppShell out of chat mode", async () => {
    // WHY: the run stays on screen; a session id in the path would turn the shell into a chat.
    renderRoute(`${RUN_PATH}?agent=${S2}&node=implement`);
    const panel = await drawer();
    expect(within(panel).getByTestId("side-chat-pane")).toHaveTextContent(S2);
    expect(sideChatPane).toHaveBeenLastCalledWith({
      childId: S2,
      fullSession: true,
      readOnly: true,
    });
    expect(shellConversationId()).toBe("");
    expect(screen.getByTestId("workflow-run-page")).toBeInTheDocument();
    expect(here()).toBe(`${RUN_PATH}?agent=${S2}&node=implement`);
  });

  it("opens from the selected step's agent chip, and Back closes it", async () => {
    renderRoute(`${RUN_PATH}?node=implement`);
    const panel = await screen.findByTestId("run-node-panel");
    const pass1 = within(panel).getByRole("list", { name: "Pass 1" });
    expect(within(panel).getByRole("list", { name: "Pass 2" })).toBeInTheDocument();
    fireEvent.click(within(pass1).getByRole("link", { name: /implementer/ }));
    expect(here()).toBe(`${RUN_PATH}?agent=${S1}&node=implement`);
    expect(within(await drawer()).getByTestId("side-chat-pane")).toHaveTextContent(S1);
    expect(shellConversationId()).toBe("");
    act(() => void navigate(-1));
    expect(here()).toBe(`${RUN_PATH}?node=implement`);
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(screen.queryByTestId("side-chat-pane")).toBeNull();
    act(() => void navigate(1));
    expect(within(await drawer()).getByTestId("side-chat-pane")).toHaveTextContent(S1);
  });

  it("opens from the keyboard and, on Escape, gives focus back to its chip", async () => {
    const user = userEvent.setup();
    renderRoute(`${RUN_PATH}?node=implement`);
    const panel = await screen.findByTestId("run-node-panel");
    const chip = within(within(panel).getByRole("list", { name: "Pass 2" })).getByRole("link");
    chip.focus();
    await user.keyboard("{Enter}");
    const open = await drawer();
    expect(within(open).getByRole("heading", { name: "Implement" })).toHaveFocus();
    await user.tab();
    expect(within(open).getByRole("link", { name: "Open in Chat" })).toHaveFocus();
    await user.tab();
    expect(within(open).getByRole("button", { name: "Close" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(here()).toBe(`${RUN_PATH}?node=implement`);
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(chip).toHaveFocus();
  });

  it("names each chip by what it opens", async () => {
    renderRoute(`${RUN_PATH}?node=implement`);
    const panel = await screen.findByTestId("run-node-panel");
    expect(
      within(panel)
        .getAllByRole("link")
        .map((link) => link.getAttribute("aria-label")),
    ).toEqual(["Open implementer’s transcript, pass 2", "Open implementer’s transcript, pass 1"]);
  });

  it("gives focus back to the chip when Back closes the drawer, else to the run's status", async () => {
    // WHY: Back closes the drawer through the URL; focus inside it must not fall to the page.
    renderRoute(`${RUN_PATH}?node=implement`);
    const panel = await screen.findByTestId("run-node-panel");
    const chip = within(panel).getByRole("link", { name: "Open implementer’s transcript, pass 1" });
    fireEvent.click(chip);
    const open = await drawer();
    expect(within(open).getByRole("heading", { name: "Implement" })).toHaveFocus();
    act(() => void navigate(-1));
    expect(screen.queryByRole("complementary")).toBeNull();
    expect(chip).toHaveFocus();
    cleanup();
    // Opened from the step's Chat page there is no chip; the run's status takes focus.
    renderRoute(`${RUN_PATH}?agent=${S1}`);
    await drawer();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.getByTestId("run-status")).toHaveFocus();
  });

  it("adds no history entry when the open transcript's chip is clicked again", async () => {
    renderRoute(`${RUN_PATH}?node=implement`);
    const panel = await screen.findByTestId("run-node-panel");
    const chip = within(panel).getByRole("link", { name: "Open implementer’s transcript, pass 2" });
    fireEvent.click(chip);
    await drawer();
    expect(chip).toHaveAttribute("aria-current", "true");
    const opened = location?.key;
    fireEvent.click(chip);
    expect(location?.key).toBe(opened);
    act(() => void navigate(-1));
    expect(here()).toBe(`${RUN_PATH}?node=implement`);
    expect(screen.queryByRole("complementary")).toBeNull();
  });

  it("keeps the run page when the transcript cannot render, and the drawer still closes", async () => {
    // WHY: the app's page boundary resets only on a new path; Close and Back change the query.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    const reported = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", reported);
    sideChatPane.mockImplementation(() => {
      throw new Error("transcript failed");
    });
    try {
      renderRoute(`${RUN_PATH}?agent=${S2}&node=implement`);
      const panel = await drawer();
      expect(within(panel).getByRole("alert")).toHaveTextContent(
        "Unable to display this step’s transcript.",
      );
      expect(screen.getByTestId("workflow-run-page")).toBeInTheDocument();
      expect(screen.getByTestId("run-actions")).toBeInTheDocument();
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(here()).toBe(`${RUN_PATH}?node=implement`);
      expect(screen.queryByRole("complementary")).toBeNull();
      act(() => void navigate(-1));
      expect(within(await drawer()).getByRole("alert")).toBeInTheDocument();
      act(() => void navigate(1));
      expect(screen.queryByRole("complementary")).toBeNull();
      act(() => void navigate(-1));
      fireEvent.click(within(await drawer()).getByRole("button", { name: "Close" }));
      expect(screen.queryByRole("complementary")).toBeNull();
      expect(screen.getByTestId("workflow-run-page")).toBeInTheDocument();
    } finally {
      window.removeEventListener("error", reported);
      quiet.mockRestore();
    }
  });

  it("opens a step's session linked without a node, as its Chat page links it", async () => {
    renderRoute(`${RUN_PATH}?agent=${S1}`);
    expect(within(await drawer()).getByTestId("side-chat-pane")).toHaveTextContent(S1);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(here()).toBe(RUN_PATH);
  });

  it("leaves the run for the session's own Chat page through Open in Chat", async () => {
    renderRoute(`${RUN_PATH}?agent=${S2}&node=implement`);
    fireEvent.click(within(await drawer()).getByRole("link", { name: "Open in Chat" }));
    expect(here()).toBe(`/c/${S2}`);
    expect(await screen.findByText("chat page")).toBeInTheDocument();
    expect(shellConversationId()).toBe(S2);
    // Same tab: Back returns to the run with the drawer open, still outside chat mode.
    act(() => void navigate(-1));
    expect(within(await drawer()).getByTestId("side-chat-pane")).toHaveTextContent(S2);
    expect(here()).toBe(`${RUN_PATH}?agent=${S2}&node=implement`);
    expect(shellConversationId()).toBe("");
  });

  it.each([
    { name: "a session outside the run", agent: "0123456789abcdef0123456789abcdef" },
    { name: "the run's anchor", agent: DETAIL.anchor_session_id },
    { name: "an empty value", agent: "" },
    { name: "an encoded path", agent: "..%2F..%2Fsettings" },
    { name: "a step's id with an encoded suffix", agent: `${S2}%2F..` },
  ])("refuses $name from the URL", async ({ agent }) => {
    // WHY: `?agent=` is untrusted; only the run's own slots open a transcript.
    renderRoute(`${RUN_PATH}?agent=${agent}&node=implement`);
    expect(await drawer()).toHaveTextContent(NOT_IN_RUN_TEXT);
    expect(sideChatPane).not.toHaveBeenCalled();
    expect(screen.queryByRole("link", { name: "Open in Chat" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(here()).toBe(`${RUN_PATH}?node=implement`);
  });

  it.each([
    { name: "the first of repeated agents", search: `?agent=${S1}&agent=${S2}&node=implement` },
    { name: "a session of another step", search: `?agent=${S1}&node=approve_change` },
    { name: "a session beside an unknown step", search: `?agent=${S1}&node=missing` },
  ])("opens $name under the session's own step", async ({ search }) => {
    // WHY: the drawer names the step the run's slot records, never what `?node=` claims.
    renderRoute(`${RUN_PATH}${search}`);
    const panel = await drawer();
    expect(within(panel).getByRole("heading", { name: "Implement" })).toBeInTheDocument();
    expect(sideChatPane).toHaveBeenLastCalledWith({
      childId: S1,
      fullSession: true,
      readOnly: true,
    });
    fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(location?.search).not.toContain("agent");
  });
});

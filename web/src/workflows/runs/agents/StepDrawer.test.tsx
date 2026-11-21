import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRef, useState, type ComponentProps, type RefObject } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useApproveHotkey } from "@/hooks/useApproveHotkey";
import type { AnyBlock, ElicitationBlock } from "@/lib/blocks";
import { FALLBACK_SERVER_INFO } from "@/lib/capabilities";
import { CapabilitiesProvider } from "@/lib/CapabilitiesContext";
import { itemsToBlocks } from "@/lib/itemsToBlocks";
import type { Session } from "@/lib/types";
import type * as SideChatPaneModule from "@/components/chat/SideChatPane";
import type * as ChatStoreModule from "@/store/chatStore";
import { ensureConversationStreamed, useChatStore, type ChatState } from "@/store/chatStore";
import { conversationRegistry } from "@/store/conversationRegistry";

// The real transcript pane renders here; only its stream bind is stubbed, so the test
// seeds the session's registry entry as a bound stream would.
vi.mock("@/store/chatStore", async (importOriginal) => ({
  ...(await importOriginal<typeof ChatStoreModule>()),
  ensureConversationStreamed: vi.fn().mockResolvedValue(undefined),
}));
// The real pane, which a test can make throw while it renders.
const paneFault = vi.hoisted(() => ({ error: null as Error | null }));
vi.mock("@/components/chat/SideChatPane", async (importOriginal) => {
  const actual = await importOriginal<typeof SideChatPaneModule>();
  return {
    SideChatPane: (props: ComponentProps<typeof actual.SideChatPane>) => {
      if (paneFault.error) throw paneFault.error;
      return <actual.SideChatPane {...props} />;
    },
  };
});

import type { RunDetail, RunView, SlotView } from "../../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../../fixtures/runViewContract";
import { evictBackgroundChat } from "../../stream/useRunStream";
import { NOT_IN_RUN_TEXT, StepDrawer } from "./StepDrawer";
import { StepDrawerFallback } from "./StepDrawerFallback";

const DETAIL = CONTRACT_DETAIL_GATE_PASS2;
const RUN_ID = DETAIL.run_id;
const PASS1 = DETAIL.slots.find((slot) => slot.engine_slot_id === "implement||a4:1:0")!;
const PASS2 = DETAIL.slots.find((slot) => slot.engine_slot_id === "implement||a4:2:0")!;
const S1 = PASS1.session_id!;
const S2 = PASS2.session_id!;
const BACKGROUND = "background-chat";
const initialStore = useChatStore.getState();

const pendingApproval: ElicitationBlock = {
  type: "elicitation",
  ctx: { agent: null, depth: 0, turn: 0, timestamp: 0, responseId: "resp_1", itemId: null },
  elicitationId: "elic_step",
  targetSessionId: null,
  message: "Allow running pytest -q?",
  phase: "tool_call",
  policyName: "ask-before-shell",
  contentPreview: "pytest -q",
  requestedSchema: {},
  url: null,
  status: "pending",
  response: null,
};

function history(text: string): AnyBlock[] {
  return itemsToBlocks([
    {
      id: `item-${text}`,
      response_id: "turn",
      type: "message",
      role: "user",
      status: "completed",
      content: [{ type: "input_text", text }],
    },
  ]);
}

/**
 * Seed a session's entry as its bound stream would: loaded, with these blocks. Seeded before
 * the drawer opens, it is an entry the drawer did not create (a background chat).
 */
function seedSession(id: string, blocks: AnyBlock[] = history(`Work of ${id}`)) {
  conversationRegistry.acquire(id).setState({ loadingConversation: false, blocks });
}

/** The pane's bind, stubbed: it creates the entry when none is live, as the real one does. */
function bindCreatesEntry() {
  vi.mocked(ensureConversationStreamed).mockImplementation(async (id: string) => {
    if (!conversationRegistry.has(id)) seedSession(id);
  });
}

/** The detail's view with one slot's status changed, as the stream would carry it. */
function viewWithStatus(slotId: string, status: SlotView["status"]): RunView {
  return {
    ...DETAIL.view!,
    slots: DETAIL.view!.slots.map((slot) => (slot.id === slotId ? { ...slot, status } : slot)),
  };
}

interface HarnessProps {
  agent: string;
  detail?: RunDetail;
  view?: RunView | null;
  focusFallback?: RefObject<HTMLElement | null>;
  findOpener?: (sessionId: string) => HTMLElement | null;
  /** The run page stops rendering the drawer, as Back or another step does. */
  hidden?: boolean;
}

function client() {
  const queryClient = new QueryClient();
  // The pane reads the session's snapshot from the shared cache, as on the Chat page.
  for (const id of [S1, S2]) {
    queryClient.setQueryData(["session", id], { id, labels: {} } as unknown as Session);
  }
  return queryClient;
}

let onClose: ReturnType<typeof vi.fn<() => void>>;

function tree(queryClient: QueryClient, props: HarnessProps) {
  return (
    <QueryClientProvider client={queryClient}>
      <CapabilitiesProvider info={FALLBACK_SERVER_INFO}>
        <TooltipProvider>
          <MemoryRouter initialEntries={[`/workflows/runs/${RUN_ID}`]}>
            <Routes>
              <Route path="/workflows/runs/:runId" element={<Closable {...props} />} />
              <Route path="/c/:conversationId" element={<p>chat page</p>} />
            </Routes>
          </MemoryRouter>
        </TooltipProvider>
      </CapabilitiesProvider>
    </QueryClientProvider>
  );
}

/** The run page's part: the drawer until it asks to close, as the URL push would end it. */
function Closable({
  agent,
  detail = DETAIL,
  view,
  focusFallback,
  findOpener,
  hidden,
}: HarnessProps) {
  const [closed, setClosed] = useState(false);
  if (closed || hidden) return <p>drawer closed</p>;
  return (
    <StepDrawer
      detail={detail}
      graph={CONTRACT_GRAPH}
      view={view === undefined ? detail.view : view}
      agent={agent}
      focusFallback={focusFallback}
      findOpener={findOpener}
      onClose={() => {
        onClose();
        setClosed(true);
      }}
    />
  );
}

function renderDrawer(props: HarnessProps) {
  const queryClient = client();
  const view = render(tree(queryClient, props));
  return { ...view, rerenderWith: (next: HarnessProps) => view.rerender(tree(queryClient, next)) };
}

const drawer = () => screen.getByRole("complementary", { name: /Implement|Step transcript/ });

beforeEach(() => {
  onClose = vi.fn<() => void>();
  paneFault.error = null;
  conversationRegistry.clear();
  useChatStore.setState({ ...initialStore, conversationId: null });
  vi.mocked(ensureConversationStreamed).mockReset().mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  conversationRegistry.clear();
  useChatStore.setState({ ...initialStore, conversationId: null });
});

describe("StepDrawer", () => {
  it.each(["session_created", "briefed", "working", "evaluating", "closing", "closed"] as const)(
    "shows a %s step's transcript read-only, with no composer",
    (status) => {
      // WHY: steering is out of scope; the drawer is for reading in every slot state.
      seedSession(S2);
      renderDrawer({ agent: S2, view: viewWithStatus("implement||a4:2:0", status) });
      const panel = drawer();
      expect(within(panel).getByRole("heading", { name: "Implement" })).toBeInTheDocument();
      expect(within(panel).getByTestId("roster-chip")).toHaveTextContent("implementer");
      expect(panel).toHaveTextContent("Pass 2");
      expect(within(panel).getByText(`Work of ${S2}`)).toBeInTheDocument();
      expect(within(panel).queryByRole("textbox")).toBeNull();
      expect(within(panel).queryByRole("button", { name: /send/i })).toBeNull();
      const line = within(panel).getByTestId("step-drawer-status");
      const expected: Partial<Record<typeof status, string>> = {
        evaluating: "Checking evidence…",
        closing: "Coral is committing this step’s work",
      };
      expect(line).toHaveTextContent(expected[status] ?? "");
      expect(ensureConversationStreamed).toHaveBeenCalledWith(S2);
    },
  );

  it("moves focus into the drawer when it opens", () => {
    seedSession(S2);
    renderDrawer({ agent: S2 });
    expect(within(drawer()).getByRole("heading", { name: "Implement" })).toHaveFocus();
  });

  it("shows a step's pending approval as its Chat page does, answered on the step's session", () => {
    // WHY: the same owner action the Inbox and the Chat page offer; nothing can be typed.
    const submitApproval = vi.fn<ChatState["submitApproval"]>().mockResolvedValue(undefined);
    useChatStore.setState({ submitApproval });
    seedSession(S2, [...history("Running the checks"), pendingApproval]);
    renderDrawer({ agent: S2 });
    const panel = drawer();
    expect(within(panel).getByText("Allow running pytest -q?")).toBeInTheDocument();
    expect(within(panel).queryByRole("textbox")).toBeNull();
    fireEvent.click(within(panel).getByRole("button", { name: /approve/i }));
    expect(submitApproval).toHaveBeenCalledTimes(1);
    const [elicitationId, action, , , sessionId] = submitApproval.mock.calls[0]!;
    expect([elicitationId, action, sessionId]).toEqual(["elic_step", "accept", S2]);
  });

  it("closes on Escape without declining the step's approval", () => {
    // WHY: Esc declines the open chat's prompt; the drawer owns Esc while it is open, even
    // when the step's session is the chat store's conversation.
    const submitApproval = vi.fn<ChatState["submitApproval"]>().mockResolvedValue(undefined);
    useChatStore.setState({ conversationId: S2 });
    useChatStore.setState({ submitApproval, blocks: [pendingApproval] });
    seedSession(S2, [pendingApproval]);
    renderHook(() => useApproveHotkey());
    renderDrawer({ agent: S2 });
    expect(drawer()).toHaveAttribute("data-escape-owner");
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByText("drawer closed")).toBeInTheDocument();
    expect(submitApproval).not.toHaveBeenCalled();
  });

  it.each([
    { how: "Close", close: () => fireEvent.click(screen.getByRole("button", { name: "Close" })) },
    { how: "Escape", close: () => fireEvent.keyDown(document.body, { key: "Escape" }) },
  ])("releases the stream it opened on $how", ({ close }) => {
    // WHY: the drawer's stream holds one of a few origin connections; closing gives it back.
    bindCreatesEntry();
    renderDrawer({ agent: S2 });
    expect(conversationRegistry.has(S2)).toBe(true);
    close();
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.getByText("drawer closed")).toBeInTheDocument();
    expect(conversationRegistry.has(S2)).toBe(false);
  });

  it("hands focus to the page when it closes from inside", () => {
    seedSession(S2);
    const fallback = createRef<HTMLButtonElement>();
    render(
      <button type="button" ref={fallback}>
        Run status
      </button>,
    );
    renderDrawer({ agent: S2, focusFallback: fallback });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(fallback.current).toHaveFocus();
  });

  it("keeps the stream of the conversation the chat store shows", () => {
    // WHY: that entry is the Chat page's own; releasing it would blank the chat it mirrors.
    bindCreatesEntry();
    renderDrawer({ agent: S2 });
    act(() => useChatStore.setState({ conversationId: S2 }));
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(conversationRegistry.has(S2)).toBe(true);
  });

  it("opens the session in Chat and leaves its stream for the Chat page", () => {
    // WHY: the Chat page binds the same stream at once; releasing it would reload it.
    bindCreatesEntry();
    renderDrawer({ agent: S2 });
    const link = within(drawer()).getByRole("link", { name: "Open in Chat" });
    expect(link).toHaveAttribute("href", `/c/${S2}`);
    fireEvent.click(link);
    expect(screen.getByText("chat page")).toBeInTheDocument();
    expect(conversationRegistry.has(S2)).toBe(true);
  });

  it("still releases on close after a modified click, which leaves the page", () => {
    // WHY: a new-tab click keeps the drawer here; only following the link in place keeps it.
    bindCreatesEntry();
    renderDrawer({ agent: S2 });
    // The browser would open a tab; jsdom cannot, so the page keeps the default.
    document.addEventListener("click", (event) => event.preventDefault(), { once: true });
    fireEvent.click(within(drawer()).getByRole("link", { name: "Open in Chat" }), {
      ctrlKey: true,
    });
    expect(screen.queryByText("chat page")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(conversationRegistry.has(S2)).toBe(false);
  });

  it("shows the pane's own Retry beside Open in Chat when the session fails to load", () => {
    conversationRegistry.acquire(S2).setState({
      loadingConversation: false,
      conversationLoadError: new Error("Session unavailable"),
    });
    renderDrawer({ agent: S2 });
    const panel = drawer();
    expect(within(panel).getByText("Couldn’t load this session")).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open in Chat" })).toBeInTheDocument();
    vi.mocked(ensureConversationStreamed).mockClear();
    fireEvent.click(within(panel).getByRole("button", { name: "Retry" }));
    expect(ensureConversationStreamed).toHaveBeenCalledWith(S2);
  });

  it.each([
    { name: "an unknown id", agent: "evil-session" },
    { name: "the run's anchor", agent: DETAIL.anchor_session_id },
    { name: "a prototype key", agent: "__proto__" },
  ])("refuses $name: not part of the run's slots", ({ agent }) => {
    // WHY: `?agent=` is untrusted; only a session the run's own detail lists may open.
    seedSession(agent);
    renderDrawer({ agent });
    const panel = drawer();
    expect(panel).toHaveTextContent(NOT_IN_RUN_TEXT);
    expect(within(panel).queryByRole("link")).toBeNull();
    expect(within(panel).queryByText(`Work of ${agent}`)).toBeNull();
    expect(ensureConversationStreamed).not.toHaveBeenCalled();
    // Nothing was retained for it, so the run stream may still free it.
    expect(evictBackgroundChat(conversationRegistry)).toBe(true);
    seedSession(agent);
    fireEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    // A session it never rendered is never released.
    expect(conversationRegistry.has(agent)).toBe(true);
  });

  it("is never what the run stream evicts while open", () => {
    // WHY: eviction frees a background chat for the run stream; the transcript being read
    // is not background.
    seedSession(BACKGROUND);
    bindCreatesEntry();
    renderDrawer({ agent: S2 });
    expect(evictBackgroundChat(conversationRegistry)).toBe(true);
    expect(conversationRegistry.has(BACKGROUND)).toBe(false);
    expect(evictBackgroundChat(conversationRegistry)).toBe(false);
    expect(conversationRegistry.has(S2)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    // Closed, it holds nothing: a new entry for the session is evictable again.
    seedSession(S2);
    expect(evictBackgroundChat(conversationRegistry)).toBe(true);
    expect(conversationRegistry.has(S2)).toBe(false);
  });

  it.each([
    {
      owner: "a dialog that has focus",
      press: () => {
        const dialog = document.createElement("div");
        dialog.setAttribute("role", "dialog");
        const button = document.createElement("button");
        dialog.append(button);
        document.body.append(dialog);
        button.focus();
        fireEvent.keyDown(button, { key: "Escape" });
        dialog.remove();
      },
    },
    {
      owner: "a handler that already took it",
      press: () => {
        const event = new KeyboardEvent("keydown", { key: "Escape", cancelable: true });
        event.preventDefault();
        window.dispatchEvent(event);
      },
    },
  ])("leaves Escape to $owner", ({ press }) => {
    // WHY: a confirm dialog over the run page closes on Escape; the drawer must stay.
    seedSession(S2);
    renderDrawer({ agent: S2 });
    press();
    expect(onClose).not.toHaveBeenCalled();
    expect(drawer()).toBeInTheDocument();
  });

  it("stays on the transcript when the run ends while it is open", () => {
    seedSession(S2);
    const view = renderDrawer({ agent: S2, view: viewWithStatus("implement||a4:2:0", "closing") });
    expect(within(drawer()).getByTestId("step-drawer-status")).toHaveTextContent(
      "Coral is committing this step’s work",
    );
    const ended: RunDetail = { ...DETAIL, status: "completed", finished_at: DETAIL.created_at };
    act(() => view.rerenderWith({ agent: S2, detail: ended }));
    const panel = drawer();
    expect(within(panel).getByText(`Work of ${S2}`)).toBeInTheDocument();
    expect(within(panel).getByTestId("step-drawer-status")).toBeEmptyDOMElement();
    expect(ensureConversationStreamed).toHaveBeenCalledTimes(1);
    expect(conversationRegistry.has(S2)).toBe(true);
    expect(evictBackgroundChat(conversationRegistry)).toBe(false);
  });

  it("opens a session the run lists only after the link was made, and protects it", () => {
    // WHY: a step's Chat page can link here before the detail lists the new session.
    const unlisted: RunDetail = {
      ...DETAIL,
      slots: DETAIL.slots.map((slot) =>
        slot.session_id === S2 ? { ...slot, session_id: null } : slot,
      ),
    };
    const view = renderDrawer({ agent: S2, detail: unlisted });
    expect(drawer()).toHaveTextContent(NOT_IN_RUN_TEXT);
    expect(ensureConversationStreamed).not.toHaveBeenCalled();
    act(() => view.rerenderWith({ agent: S2 }));
    expect(ensureConversationStreamed).toHaveBeenCalledWith(S2);
    // The entry appears after the drawer mounted, as the stream's bind (or a Retry) makes it.
    act(() => seedSession(S2));
    seedSession(BACKGROUND);
    expect(within(drawer()).getByText(`Work of ${S2}`)).toBeInTheDocument();
    expect(evictBackgroundChat(conversationRegistry)).toBe(true);
    expect(evictBackgroundChat(conversationRegistry)).toBe(false);
    expect(conversationRegistry.has(S2)).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(conversationRegistry.has(S2)).toBe(false);
  });

  it("shows one step at a time: another session releases the one it replaced", () => {
    bindCreatesEntry();
    const view = renderDrawer({ agent: S2 });
    act(() => view.rerenderWith({ agent: S1 }));
    expect(conversationRegistry.has(S2)).toBe(false);
    expect(within(drawer()).getByText(`Work of ${S1}`)).toBeInTheDocument();
    expect(drawer()).toHaveTextContent("Pass 1");
    expect(screen.getAllByRole("complementary")).toHaveLength(1);
    expect(evictBackgroundChat(conversationRegistry)).toBe(false);
  });

  it("leaves an entry it did not open: a background chat and its unsent draft survive", () => {
    // WHY: a failed send's draft is the only copy of what the person typed into the step's
    // Chat page; the registry's own eviction never drops it, and neither may the drawer.
    conversationRegistry.acquire(S2).setState({
      loadingConversation: false,
      blocks: history(`Work of ${S2}`),
      failedSendDraft: { conversationId: S2, text: "Also fix the flaky test", files: [] },
    });
    renderDrawer({ agent: S2 });
    expect(within(drawer()).getByText(`Work of ${S2}`)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(conversationRegistry.peek(S2)?.getState().failedSendDraft?.text).toBe(
      "Also fix the flaky test",
    );
    // Closed, it is an ordinary background entry again, which eviction still protects.
    expect(evictBackgroundChat(conversationRegistry)).toBe(false);
  });

  it("keeps a transcript that cannot render inside the drawer, which still closes", () => {
    // WHY: one faulty transcript must not take the run's gate card and controls with it.
    const quiet = vi.spyOn(console, "error").mockImplementation(() => {});
    const reported = (event: ErrorEvent) => event.preventDefault();
    window.addEventListener("error", reported);
    try {
      paneFault.error = new Error("transcript failed");
      bindCreatesEntry();
      renderDrawer({ agent: S2 });
      const panel = drawer();
      expect(within(panel).getByRole("alert")).toHaveTextContent(
        "Unable to display this step’s transcript.",
      );
      expect(within(panel).getByRole("link", { name: "Open in Chat" })).toBeInTheDocument();
      fireEvent.keyDown(document.body, { key: "Escape" });
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(screen.getByText("drawer closed")).toBeInTheDocument();
      // The drawer had not created an entry yet: the pane threw before it could bind.
      expect(ensureConversationStreamed).not.toHaveBeenCalled();
    } finally {
      window.removeEventListener("error", reported);
      quiet.mockRestore();
    }
  });

  it("shows a step's question form as its Chat page does, with its typed answer", () => {
    // WHY (R44): every prompt kind renders as on the step's Chat page; a question takes a
    // typed answer, which goes to the step's session. Escape there keeps the typing.
    const submitApproval = vi.fn<ChatState["submitApproval"]>().mockResolvedValue(undefined);
    useChatStore.setState({ submitApproval });
    const question: ElicitationBlock = {
      ...pendingApproval,
      elicitationId: "elic_question",
      message: "Claude has questions",
      phase: "pre_tool_use",
      contentPreview: "",
      askUserQuestion: {
        questions: [
          {
            question: "Which framework?",
            header: "Framework",
            options: [{ label: "React" }, { label: "Vue" }],
            multiSelect: false,
          },
        ],
      },
    };
    seedSession(S2, [...history("Choosing a framework"), question]);
    renderDrawer({ agent: S2 });
    const panel = drawer();
    expect(within(panel).getByText("Which framework?")).toBeInTheDocument();
    expect(within(panel).getByRole("radio", { name: "React" })).toBeInTheDocument();
    expect(within(panel).getByRole("radio", { name: "Vue" })).toBeInTheDocument();
    // The one text field is the question's own custom answer: no composer.
    const custom = within(panel).getByRole("textbox", { name: "Custom answer" });
    expect(within(panel).getAllByRole("textbox")).toEqual([custom]);
    fireEvent.change(custom, { target: { value: "Svelte" } });
    fireEvent.keyDown(custom, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
    expect(custom).toHaveValue("Svelte");
    fireEvent.click(within(panel).getByRole("button", { name: /submit/i }));
    expect(submitApproval).toHaveBeenCalledTimes(1);
    const [elicitationId, action, content, , sessionId] = submitApproval.mock.calls[0]!;
    expect([elicitationId, action, sessionId]).toEqual(["elic_question", "accept", S2]);
    expect(JSON.stringify(content)).toContain("Svelte");
  });

  it("shows a step's session-wide permission choices as its Chat page does", () => {
    // WHY (R44): these change how the step's session asks for the rest of its life; the
    // drawer shows them as the Chat page does, and the human brief lists them.
    const permission: ElicitationBlock = {
      ...pendingApproval,
      elicitationId: "elic_edit",
      allowAutoMode: true,
      allowAllEdits: true,
    };
    const webFetch: ElicitationBlock = {
      ...pendingApproval,
      elicitationId: "elic_fetch",
      rememberScope: { tool: "WebFetch", host: "docs.example.com" },
    };
    seedSession(S2, [permission]);
    const view = renderDrawer({ agent: S2 });
    const panel = drawer();
    expect(
      within(panel).getByRole("button", { name: /Approve & switch to auto mode/ }),
    ).toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: /Accept & allow all edits/ }),
    ).toBeInTheDocument();
    view.unmount();
    seedSession(S2, [webFetch]);
    renderDrawer({ agent: S2 });
    expect(
      within(drawer()).getByRole("button", { name: /don't ask again for docs.example.com/ }),
    ).toBeInTheDocument();
  });

  it("leaves Escape to a fullscreen view opened from the transcript", () => {
    // WHY: one Escape closes a fullscreen diagram; the drawer under it stays open.
    seedSession(S2);
    renderDrawer({ agent: S2 });
    const overlay = document.createElement("div");
    overlay.setAttribute("data-fullscreen-overlay", "");
    document.body.append(overlay);
    try {
      fireEvent.keyDown(window, { key: "Escape" });
      expect(onClose).not.toHaveBeenCalled();
    } finally {
      overlay.remove();
    }
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("leaves Escape to text typed outside the drawer", () => {
    seedSession(S2);
    render(<textarea aria-label="Gate note" />);
    renderDrawer({ agent: S2 });
    const note = screen.getByRole("textbox", { name: "Gate note" });
    note.focus();
    fireEvent.keyDown(note, { key: "Escape" });
    expect(onClose).not.toHaveBeenCalled();
  });

  it.each([
    { how: "Close", close: () => fireEvent.click(screen.getByRole("button", { name: "Close" })) },
    { how: "the page dropping it (Back)", close: null },
  ])("gives focus back to the chip that opened it on $how", ({ close }) => {
    // WHY: a keyboard user returns to where they were, not to the top of the page.
    seedSession(S2);
    const fallback = createRef<HTMLButtonElement>();
    render(
      <>
        <button type="button" ref={fallback}>
          Run status
        </button>
        <a href="#chip" data-chip={S2}>
          Open implementer’s transcript
        </a>
      </>,
    );
    const chip = screen.getByRole("link", { name: "Open implementer’s transcript" });
    const findOpener = (id: string) => (id === S2 ? chip : null);
    const view = renderDrawer({ agent: S2, focusFallback: fallback, findOpener });
    expect(within(drawer()).getByRole("heading", { name: "Implement" })).toHaveFocus();
    if (close) close();
    else view.rerenderWith({ agent: S2, focusFallback: fallback, findOpener, hidden: true });
    expect(screen.getByText("drawer closed")).toBeInTheDocument();
    expect(chip).toHaveFocus();
  });

  it("leaves focus where it is when it closes with focus elsewhere", () => {
    seedSession(S2);
    const fallback = createRef<HTMLButtonElement>();
    render(
      <>
        <button type="button" ref={fallback}>
          Run status
        </button>
        <button type="button">Another step</button>
      </>,
    );
    const view = renderDrawer({ agent: S2, focusFallback: fallback });
    const other = screen.getByRole("button", { name: "Another step" });
    other.focus();
    view.rerenderWith({ agent: S2, focusFallback: fallback, hidden: true });
    expect(other).toHaveFocus();
  });

  it("keeps focus where the person moved it when a reread fills the drawer in", () => {
    // WHY: the detail can list the session only after the drawer opened; that is not a
    // new opening, so focus is not taken back to the heading.
    const unlisted: RunDetail = {
      ...DETAIL,
      slots: DETAIL.slots.map((slot) =>
        slot.session_id === S2 ? { ...slot, session_id: null } : slot,
      ),
    };
    seedSession(S2);
    const view = renderDrawer({ agent: S2, detail: unlisted });
    const close = within(drawer()).getByRole("button", { name: "Close" });
    close.focus();
    act(() => view.rerenderWith({ agent: S2 }));
    expect(within(drawer()).getByText(`Work of ${S2}`)).toBeInTheDocument();
    expect(close).toHaveFocus();
  });

  it("keeps its status region in the tree, announcing a status when one appears", () => {
    seedSession(S2);
    const view = renderDrawer({ agent: S2 });
    const region = within(drawer()).getByRole("status");
    expect(region).toBe(within(drawer()).getByTestId("step-drawer-status"));
    expect(region).toBeEmptyDOMElement();
    act(() =>
      view.rerenderWith({ agent: S2, view: viewWithStatus("implement||a4:2:0", "evaluating") }),
    );
    expect(within(drawer()).getByRole("status")).toBe(region);
    expect(region).toHaveTextContent("Checking evidence…");
  });
});

describe("StepDrawerFallback", () => {
  it("says the transcript is loading in the drawer's place", () => {
    render(<StepDrawerFallback />);
    expect(screen.getByTestId("step-drawer-loading")).toHaveTextContent(
      "Loading the step’s transcript…",
    );
    expect(screen.queryByRole("complementary")).toBeNull();
  });
});

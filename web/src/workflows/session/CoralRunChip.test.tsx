import { act, cleanup, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ComponentProps, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { TooltipProvider } from "@/components/ui/tooltip";
import type * as identityModule from "@/lib/identity";
import type { Session } from "@/lib/types";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));

import { ChatHeader } from "@/shell/ChatHeader";
import type { CoralInfo } from "../api/types";
import { CORAL_INFO_QUERY_KEY } from "../gate/useCoralInfo";
import { CoralRunChip } from "./CoralRunChip";
import { ROLE_LABEL, RUN_ID_LABEL } from "./coralLabels";

const RUN_ID = "84170e76f35c7a90d1280a24a7230fc9";
const SESSION_ID = "b04398ed7d8d2ba8f0154876974f9078";
const CORAL_ON: CoralInfo = { enabled: true, version: "1", sub_features: {} };

function runSession(role: string | null, runId: string = RUN_ID): Session {
  const labels: Record<string, string> = { [RUN_ID_LABEL]: runId };
  if (role !== null) labels[ROLE_LABEL] = role;
  return { id: SESSION_ID, labels } as unknown as Session;
}

/** A client whose cache holds what AppShell and the Coral gate would have read. */
function cachedClient({ session, info }: { session?: Session; info?: CoralInfo }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (session) client.setQueryData(["session", SESSION_ID], session);
  if (info) client.setQueryData(CORAL_INFO_QUERY_KEY, info);
  return client;
}

function renderWith(client: QueryClient, ui: ReactNode) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/c/${SESSION_ID}`]}>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

const chip = (client: QueryClient) =>
  renderWith(client, <CoralRunChip conversationId={SESSION_ID} />);

beforeEach(() => {
  authenticatedFetch.mockReset();
  authenticatedFetch.mockImplementation(async (input: RequestInfo | URL) => {
    if (String(input).includes("/v1/coral/info")) {
      return new Response(JSON.stringify(CORAL_ON), { status: 200 });
    }
    return new Response("{}", { status: 404 });
  });
});

afterEach(cleanup);

describe("CoralRunChip", () => {
  it.each([
    { role: "run", what: "the run's anchor", href: `/workflows/runs/${RUN_ID}` },
    { role: "orchestrator", what: "the orchestrator", href: `/workflows/runs/${RUN_ID}` },
    {
      role: "step",
      what: "a step",
      href: `/workflows/runs/${RUN_ID}?agent=${SESSION_ID}`,
    },
  ])("links $what's session back to its run", ({ role, href }) => {
    // WHY: anyone arriving at a run's session from a link or the session list can get back.
    chip(cachedClient({ session: runSession(role), info: CORAL_ON }));
    const element = screen.getByTestId("coral-run-chip");
    expect(element).toHaveTextContent("Part of a run");
    expect(within(element).getByRole("link", { name: "Open run" })).toHaveAttribute("href", href);
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("renders nothing and fetches nothing for a session outside any run", () => {
    // WHY: every Chat page renders the chip; ordinary sessions must cost nothing.
    chip(cachedClient({ session: { id: SESSION_ID, labels: {} } as unknown as Session }));
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
    cleanup();
    chip(cachedClient({}));
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("renders nothing while Coral is off", () => {
    chip(cachedClient({ session: runSession("run"), info: { ...CORAL_ON, enabled: false } }));
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
  });

  it("asks whether Coral is on only for a run's session, and shows once it is", async () => {
    chip(cachedClient({ session: runSession("step") }));
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
    expect(await screen.findByTestId("coral-run-chip")).toBeInTheDocument();
    expect(authenticatedFetch.mock.calls.map(([input]) => String(input))).toEqual([
      "/v1/coral/info",
    ]);
  });

  it("appears once the session snapshot lands, without fetching the session itself", async () => {
    // WHY: on a cold load the header renders before AppShell's session read resolves.
    const client = cachedClient({ info: CORAL_ON });
    chip(client);
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
    act(() => client.setQueryData(["session", SESSION_ID], runSession("step")));
    expect(await screen.findByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      `/workflows/runs/${RUN_ID}?agent=${SESSION_ID}`,
    );
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });

  it("builds the run's link from its id, never as raw path text", () => {
    // WHY: the label is server-set, but the path still escapes it rather than trusting it.
    chip(cachedClient({ session: runSession("run", "../../settings?x=1"), info: CORAL_ON }));
    expect(screen.getByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      "/workflows/runs/..%2F..%2Fsettings%3Fx%3D1",
    );
  });
});

// The desktop header reads only the mobile menu's open flags, all falsy here.
const MOBILE_MENU = {} as ComponentProps<typeof ChatHeader>["mobileMenu"];

function header(client: QueryClient) {
  return renderWith(
    client,
    <TooltipProvider>
      <ChatHeader
        sidebarOpen
        onOpenSidebar={() => {}}
        isChildSession={false}
        conversationId={SESSION_ID}
        conversationTitle="Fix the flaky test"
        projectName={null}
        boundAgent={undefined}
        wrapperLabel={null}
        canShare={false}
        canFork={false}
        onShare={() => {}}
        onFork={() => {}}
        hasAgentInfo={false}
        onAgentInfo={() => {}}
        hasHeaderMenu={false}
        showFilesPanel={false}
        hasRailContent={false}
        rightPanelOpen={false}
        onToggleRightPanel={() => {}}
        mobileMenu={MOBILE_MENU}
      />
    </TooltipProvider>,
  );
}

describe("ChatHeader's run chip", () => {
  it("leads the anchor's Chat page back to its run", () => {
    header(cachedClient({ session: runSession("run"), info: CORAL_ON }));
    expect(screen.getByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      `/workflows/runs/${RUN_ID}`,
    );
  });

  it("shows nothing on an ordinary session's header", () => {
    header(cachedClient({ session: { id: SESSION_ID, labels: {} } as unknown as Session }));
    expect(screen.queryByTestId("coral-run-chip")).toBeNull();
    expect(authenticatedFetch).not.toHaveBeenCalledWith("/v1/coral/info", expect.anything());
  });
});

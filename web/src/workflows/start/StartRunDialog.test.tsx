import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as identityModule from "@/lib/identity";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", async (importActual) => ({
  ...(await importActual<typeof identityModule>()),
  authenticatedFetch,
}));
const keys = vi.hoisted(() => ({ made: 0 }));
vi.mock("@/lib/randomUUID", () => ({
  randomUUID: () => {
    keys.made += 1;
    return `key-${keys.made}`;
  },
}));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => "alice" }));
vi.mock("@/hooks/useHosts", () => ({
  useHosts: () => ({
    isPending: false,
    data: [
      { host_id: "h1", name: "Laptop", status: "online" },
      { host_id: "h2", name: "Desktop", status: "online" },
      { host_id: "h3", name: "Offline box", status: "offline" },
    ],
  }),
}));
// A folder name with spaces, quotes, markup, a backslash, an escape-like `%20` and non-ASCII.
const folders = vi.hoisted(() => ({
  odd: '/Users/me/My Repo (copy)/naïve 日本 "q" & <b> \\ %20 #x',
}));
vi.mock("@/shell/WorkspacePickerDialog", () => ({
  WorkspacePickerDialog: ({
    open,
    hostId,
    onConfirm,
  }: {
    open: boolean;
    hostId: string | null;
    onConfirm: (path: string) => void;
  }) =>
    open ? (
      <div>
        {["/repo", "/other", folders.odd].map((path) => (
          <button key={path} type="button" onClick={() => onConfirm(path)}>
            {`pick ${path} on ${hostId}`}
          </button>
        ))}
      </div>
    ) : null,
}));

import type { RunSummary } from "../api/generated/coralApi";
import { MAX_RETRY_AFTER_MS, runsListQueryKey } from "../api/runsApi";
import { jsonResponse } from "../fixtures/runStreamServer";
import { coralScope } from "../shared/viewerScope";
import { StartRunDialog } from "./StartRunDialog";

const WORKFLOW_ID = "0123456789abcdef0123456789abcdef";
const RUN_ID = "84170e76f35c7a90d1280a24a7230fc9";

/** The runs history's unfiltered first page, which a start makes stale. */
const RUNS_LIST_KEY = runsListQueryKey(coralScope("alice", "/"), {
  statuses: [],
  workflowId: null,
});

const SUMMARY: RunSummary = {
  run_id: RUN_ID,
  workflow_id: WORKFLOW_ID,
  version_id: "",
  title: "Demo",
  status: "starting",
  pause_reason: null,
  created_at: 1_767_268_000,
  updated_at: 1_767_268_000,
  finished_at: null,
  activation_count: 0,
  allowed_actions: ["cancel"],
  spend: null,
  run_branch: "coral/r-0a1b2c3d4e5f/base",
};

const OK_PREFLIGHT = {
  ok: true,
  items: [
    { check: "auth", status: "ok", message: "Claude has an API credential.", fix: null },
    { check: "host_online", status: "ok", message: "The host is connected.", fix: null },
  ],
  estimate: { sessions: 4 },
};

const FAIL_PREFLIGHT = {
  ok: false,
  items: [
    {
      check: "auth",
      status: "fail",
      message: "Workflows with an orchestrator need an Anthropic API key.",
      fix: { target: "add_api_key", href: null },
    },
  ],
  estimate: { sessions: 4 },
};

const refusal = (
  status: number,
  code: string,
  message: string,
  headers: Record<string, string> = {},
) => jsonResponse(status, { error: { code, message, details: null } }, headers);

/** The start route's answers in turn; the last repeats. */
let answers: (() => Response | Promise<Response>)[];
/** The preflight route's answers in turn; the last repeats. */
let preflightAnswers: (() => Response | Promise<Response>)[];
/** What each notice the dialog raised said. */
let notices: ReactNode[];
const onNotice = (event: Event) => notices.push((event as CustomEvent).detail.content);

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

/** Somewhere else in the app the person can go while a start is in flight. */
function GoElsewhere() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate("/elsewhere")}>
      go elsewhere
    </button>
  );
}

/** An answer the test releases. */
function held(): { promise: Promise<Response>; release: (response: Response) => void } {
  let release: (response: Response) => void = () => {};
  const promise = new Promise<Response>((resolve) => {
    release = resolve;
  });
  return { promise, release: (response) => release(response) };
}

function tree(open: boolean, onOpenChange: (open: boolean) => void) {
  return (
    <MemoryRouter initialEntries={["/workflows/demo"]}>
      <Routes>
        <Route
          path="/workflows/demo"
          element={
            <>
              <GoElsewhere />
              <StartRunDialog
                workflowId={WORKFLOW_ID}
                workflowKey="demo"
                open={open}
                onOpenChange={onOpenChange}
              />
            </>
          }
        />
        <Route path="*" element={<Where />} />
      </Routes>
    </MemoryRouter>
  );
}

function renderDialog() {
  const client = new QueryClient();
  client.setQueryData(RUNS_LIST_KEY, { pages: [], pageParams: [] });
  const onOpenChange = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>{tree(true, onOpenChange)}</QueryClientProvider>,
  );
  const reopen = (open: boolean) =>
    view.rerender(
      <QueryClientProvider client={client}>{tree(open, onOpenChange)}</QueryClientProvider>,
    );
  const runsListStale = () => client.getQueryState(RUNS_LIST_KEY)?.isInvalidated;
  return { onOpenChange, reopen, runsListStale };
}

const run = (ms = 0) => act(() => vi.advanceTimersByTimeAsync(ms));
const startButton = () => screen.getByRole("button", { name: "Start run" });

/** Every start body the dialog posted, parsed. */
function posted(): Record<string, unknown>[] {
  return authenticatedFetch.mock.calls
    .filter(([url]) => url === "/v1/coral/runs")
    .map(([, init]) => {
      expect((init as RequestInit).method).toBe("POST");
      expect(new Headers((init as RequestInit).headers).get("Content-Type")).toBe(
        "application/json",
      );
      return JSON.parse((init as RequestInit).body as string) as Record<string, unknown>;
    });
}

/** Every preflight body the dialog posted, parsed. */
function preflighted(): Record<string, unknown>[] {
  return authenticatedFetch.mock.calls
    .filter(([url]) => url === "/v1/coral/runs:preflight")
    .map(([, init]) => JSON.parse((init as RequestInit).body as string) as Record<string, unknown>);
}

const keysPosted = () => posted().map((body) => body.start_key);

async function chooseHost(name: string) {
  fireEvent.click(screen.getByRole("button", { name }));
  await run();
}

async function chooseFolder(path: string, hostId: string) {
  fireEvent.click(screen.getByRole("button", { name: "Choose folder" }));
  await run();
  fireEvent.click(screen.getByRole("button", { name: `pick ${path} on ${hostId}`, hidden: true }));
  await run();
}

async function start() {
  fireEvent.click(startButton());
  await run();
}

beforeEach(() => {
  vi.useFakeTimers();
  keys.made = 0;
  notices = [];
  window.addEventListener("omnigent:toast", onNotice);
  answers = [() => jsonResponse(201, SUMMARY)];
  preflightAnswers = [() => jsonResponse(200, OK_PREFLIGHT)];
  authenticatedFetch.mockImplementation(async (url: string) => {
    const queue = url === "/v1/coral/runs:preflight" ? preflightAnswers : answers;
    const answer = queue.length > 1 ? queue.shift()! : queue[0]!;
    return answer();
  });
});

afterEach(() => {
  window.removeEventListener("omnigent:toast", onNotice);
  cleanup();
  authenticatedFetch.mockReset();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("StartRunDialog", () => {
  it("lists only online hosts, and enables Start once a host and folder are chosen", async () => {
    renderDialog();
    await run();
    expect(screen.queryByRole("button", { name: "Offline box" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose folder" })).toBeDisabled();
    expect(startButton()).toBeDisabled();

    await chooseHost("Laptop");
    expect(startButton()).toBeDisabled();
    await chooseFolder("/repo", "h1");
    expect(startButton()).toBeEnabled();
  });

  it("asks preflight once a host is chosen and gates Start on failures", async () => {
    preflightAnswers = [() => jsonResponse(200, FAIL_PREFLIGHT)];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    expect(preflighted()).toEqual([{ workflow_id: WORKFLOW_ID, host_id: "h1" }]);
    expect(screen.getByTestId("preflight")).toBeInTheDocument();
    expect(screen.getByText(/need an Anthropic API key/)).toBeInTheDocument();
    await chooseFolder("/repo", "h1");
    expect(startButton()).toBeDisabled();
  });

  it("enables Start after a passing preflight when host and folder are chosen", async () => {
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    expect(screen.getByTestId("preflight")).toBeInTheDocument();
    expect(startButton()).toBeEnabled();
  });

  it("posts the start once, opens the new run and refreshes the runs history", async () => {
    // WHY: the server needs the stored workflow id and the repository root, with a start key;
    // the history must list the new run when the person goes back to it.
    const { onOpenChange, runsListStale } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    expect(runsListStale()).toBe(false);
    fireEvent.click(startButton());
    fireEvent.click(startButton());
    await run();

    expect(posted()).toEqual([
      {
        workflow_id: WORKFLOW_ID,
        start_key: expect.stringMatching(/^key-\d+$/),
        host_id: "h1",
        repo_path: "/repo",
      },
    ]);
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
    expect(runsListStale()).toBe(true);
  });

  it("opens the run a replayed start key answers", async () => {
    // WHY: a 200 is the run this key already started, so it is the one to open.
    answers = [() => jsonResponse(200, SUMMARY)];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
  });

  it("reuses the start key on a retry, and makes a new one when the host or folder changes", async () => {
    // WHY: a retried POST of the same start replays its run instead of starting a second one.
    answers = [() => refusal(503, "server_busy", "The server is busy; try again.")];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    await start();
    const [first, retried] = keysPosted();
    expect(retried).toBe(first);

    await chooseFolder("/other", "h1");
    await start();
    await chooseHost("Desktop");
    await chooseFolder("/other", "h2");
    await start();
    const [, , newFolder, newHost] = keysPosted();
    expect(new Set([first, newFolder, newHost]).size).toBe(3);
    expect(posted().at(-1)).toMatchObject({ host_id: "h2", repo_path: "/other" });
  });

  it("keeps the start key across a dropped connection, so the retry opens the run it started", async () => {
    // WHY: a POST whose answer was lost may have started the run; the retry must replay it.
    answers = [
      () => Promise.reject(new TypeError("Failed to fetch")),
      () => jsonResponse(200, SUMMARY),
    ];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't start the run. Try again.");
    expect(startButton()).toBeEnabled();

    await start();
    const [first, retried] = keysPosted();
    expect(retried).toBe(first);
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
  });

  it("posts and shows the folder path exactly as picked", async () => {
    // WHY: the host resolves the path itself; any trimming or escaping names another folder.
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder(folders.odd, "h1");
    expect(screen.getByText(folders.odd).tagName).toBe("CODE");
    await start();
    expect(posted()).toEqual([expect.objectContaining({ repo_path: folders.odd })]);
  });

  it("makes a new start key each time the dialog opens", async () => {
    answers = [() => refusal(500, "internal", "Boom.")];
    const { reopen } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();

    reopen(false);
    await run();
    reopen(true);
    await run();
    await start();
    const [first, second] = keysPosted();
    expect(second).not.toBe(first);
    expect(posted()[1]).toMatchObject({ host_id: "h1", repo_path: "/repo" });
  });

  it("never calls crypto.randomUUID itself", async () => {
    // WHY: plain-http self-hosted origins have no crypto.randomUUID.
    const direct = typeof crypto.randomUUID === "function" ? vi.spyOn(crypto, "randomUUID") : null;
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(keysPosted()).toEqual([expect.stringMatching(/^key-\d+$/)]);
    if (direct) expect(direct).not.toHaveBeenCalled();
  });

  it.each([
    [
      "a folder that is not a repository root",
      () => refusal(400, "not_a_git_repo", "Not a git repository."),
      "That folder isn't the root of a git repository.",
    ],
    [
      "a host the owner cannot use",
      () => refusal(403, "not_permitted", "Not permitted."),
      "You can't start runs on this host.",
    ],
    [
      "a workflow that is gone",
      () => refusal(404, "not_found", "Workflow not found."),
      "This workflow no longer exists.",
    ],
    [
      "a start key used for another request",
      () =>
        refusal(409, "start_key_conflict", "This start key started a run with another request."),
      "This start key started a run with another request.",
    ],
    [
      "a worktree the host could not make",
      () => refusal(409, "worktree_failed", "The run's worktree could not be created."),
      "The run's worktree could not be created.",
    ],
    [
      "a workflow that cannot run",
      () => refusal(422, "not_runnable", "The workflow has no start node."),
      "This workflow can't run yet: The workflow has no start node.",
    ],
    [
      "an offline host",
      () => refusal(503, "host_offline", "No host can be reached from this server."),
      "The host is offline.",
    ],
    [
      "a busy server",
      () => refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "1" }),
      "The server is busy; try again.",
    ],
    [
      "a request the server could not read",
      () => refusal(422, "validation_failed", "Bad host."),
      "Couldn't start the run. Try again.",
    ],
    [
      "a conflict outside Coral's envelope",
      () => jsonResponse(409, { detail: "Conflict" }),
      "Couldn't start the run. Try again.",
    ],
    [
      "a server error",
      () => refusal(500, "internal", "Boom."),
      "Couldn't start the run. Try again.",
    ],
    [
      "a dropped connection",
      () => Promise.reject(new TypeError("Failed to fetch")),
      "Couldn't start the run. Try again.",
    ],
  ])("explains %s and stays open", async (_name, answer, text) => {
    answers = [answer];
    const { onOpenChange } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByRole("alert")).toHaveTextContent(text);
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(screen.queryByTestId("where")).not.toBeInTheDocument();
  });

  it("clears a refusal once the host or folder changes", async () => {
    answers = [() => refusal(403, "not_permitted", "Not permitted.")];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    await chooseHost("Desktop");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("holds Start for the busy server's Retry-After", async () => {
    // WHY: an immediate retry would be refused again.
    answers = [
      () => refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "2" }),
      () => jsonResponse(201, SUMMARY),
    ];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(startButton()).toBeDisabled();
    await run(1_999);
    expect(startButton()).toBeDisabled();
    await run(1);
    expect(startButton()).toBeEnabled();
    await start();
    const [first, retried] = keysPosted();
    expect(retried).toBe(first);
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
  });

  it.each([
    ["missing", {}],
    ["zero", { "Retry-After": "0" }],
    ["not a number", { "Retry-After": "soon" }],
  ])("does not hold Start when the busy server's Retry-After is %s", async (_name, headers) => {
    // WHY: with no usable hint the person decides when to retry.
    answers = [() => refusal(503, "server_busy", "The server is busy; try again.", headers)];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByRole("alert")).toHaveTextContent("The server is busy; try again.");
    expect(startButton()).toBeEnabled();
  });

  it("holds Start for at most a minute, whatever Retry-After says", async () => {
    answers = [
      () =>
        refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "3600" }),
    ];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(startButton()).toBeDisabled();
    await run(MAX_RETRY_AFTER_MS);
    expect(startButton()).toBeEnabled();
  });

  it("keeps the hold when the same folder is picked again, and lifts it for another", async () => {
    // WHY: the same inputs would be refused again; other inputs are another start.
    answers = [
      () => refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "30" }),
    ];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(startButton()).toBeDisabled();

    await chooseFolder("/repo", "h1");
    expect(startButton()).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("The server is busy; try again.");

    await chooseFolder("/other", "h1");
    expect(startButton()).toBeEnabled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("locks the host and folder while a start is in flight, so its run is the one shown", async () => {
    // WHY: an answer must never land on inputs the person picked after clicking Start.
    const reply = held();
    answers = [() => reply.promise];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(screen.getByRole("button", { name: "Laptop" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Desktop" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Choose folder" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Desktop" }));
    await run();
    expect(screen.getByText("/repo")).toBeInTheDocument();

    reply.release(jsonResponse(201, SUMMARY));
    await run();
    expect(posted()).toEqual([expect.objectContaining({ host_id: "h1", repo_path: "/repo" })]);
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
  });

  it("unlocks the inputs with the refusal shown once an in-flight start fails", async () => {
    const reply = held();
    answers = [() => reply.promise];
    renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    reply.release(refusal(503, "host_offline", "No host can be reached from this server."));
    await run();
    expect(screen.getByRole("alert")).toHaveTextContent("The host is offline.");
    expect(screen.getByRole("button", { name: "Desktop" })).toBeEnabled();
    await chooseHost("Desktop");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("leaves the person where they are when a start lands after the dialog closed", async () => {
    // WHY: someone who closed the dialog and moved on is not pulled onto the run; a notice
    // links to it instead.
    const reply = held();
    answers = [() => reply.promise];
    const { reopen, onOpenChange, runsListStale } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    reopen(false);
    await run();
    fireEvent.click(screen.getByRole("button", { name: "go elsewhere" }));
    await run();

    reply.release(jsonResponse(201, SUMMARY));
    await run();
    expect(screen.getByTestId("where")).toHaveTextContent("/elsewhere");
    expect(onOpenChange).not.toHaveBeenCalled();
    expect(runsListStale()).toBe(true);
    expect(notices).toHaveLength(1);
    cleanup();
    render(<MemoryRouter>{notices[0]}</MemoryRouter>);
    expect(screen.getByText(/The run started\./)).toBeInTheDocument();
    expect(within(document.body).getByRole("link", { name: "Open run" })).toHaveAttribute(
      "href",
      `/workflows/runs/${RUN_ID}`,
    );
  });

  it("still opens the run when the dialog was closed and opened again before it landed", async () => {
    const reply = held();
    answers = [() => reply.promise];
    const { reopen } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    reopen(false);
    await run();
    reopen(true);
    await run();
    // The start is still in flight, so the inputs stay locked.
    expect(screen.getByRole("button", { name: "Desktop" })).toBeDisabled();
    reply.release(jsonResponse(201, SUMMARY));
    await run();
    expect(screen.getByTestId("where")).toHaveTextContent(`/workflows/runs/${RUN_ID}`);
    expect(notices).toHaveLength(0);
  });

  it("opens clean after a refusal: no old alert and no hold", async () => {
    // WHY: a new opening is a new start with a new key.
    answers = [
      () => refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "30" }),
    ];
    const { reopen } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    expect(startButton()).toBeDisabled();
    reopen(false);
    await run();
    reopen(true);
    await run();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(startButton()).toBeEnabled();
  });

  it("shows nothing of a refusal that landed while the dialog was closed", async () => {
    const reply = held();
    answers = [() => reply.promise];
    const { reopen } = renderDialog();
    await run();
    await chooseHost("Laptop");
    await chooseFolder("/repo", "h1");
    await start();
    reopen(false);
    await run();
    reply.release(
      refusal(503, "server_busy", "The server is busy; try again.", { "Retry-After": "30" }),
    );
    await run();
    reopen(true);
    await run();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(startButton()).toBeEnabled();
    expect(notices).toHaveLength(0);
  });
});

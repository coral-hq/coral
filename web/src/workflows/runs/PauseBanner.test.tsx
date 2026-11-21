import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { PauseCause, RunView } from "../api/generated/coralApi";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../fixtures/runViewContract";
import { isolated, PAUSE_MESSAGES, type GraphNodeNames } from "../shared/pauseCopy";
import { PauseBanner } from "./PauseBanner";

const OPEN_VIEW = CONTRACT_DETAIL_GATE_PASS2.view!;
const USER_CAUSE: PauseCause = { reason: "user", detail: "", subject: "" };
// The recording's graph, plus a decision the orchestrator answers.
const GRAPH: GraphNodeNames = {
  nodes: [...CONTRACT_GRAPH.nodes, { id: "choose", name: "Choose path" }],
};

function pausedView(changes: Partial<RunView> = {}): RunView {
  return { ...OPEN_VIEW, status: "paused", causes: [USER_CAUSE], ...changes };
}

function renderBanner(
  reason: string | null,
  view: RunView | null,
  graph: GraphNodeNames | null = GRAPH,
) {
  return render(<PauseBanner reason={reason} view={view} graph={graph} />);
}

const items = () =>
  within(screen.getByRole("region"))
    .queryAllByRole("listitem")
    .map((item) => item.textContent);

afterEach(cleanup);

describe("PauseBanner", () => {
  it("names a pause the owner made and says so", () => {
    // WHY: the recorded run is paused by its owner with the gate still open.
    renderBanner("user", pausedView());
    const banner = screen.getByRole("region", { name: "Paused: by you" });
    expect(banner).toHaveTextContent("The run paused.");
    expect(items()).toEqual([]);
  });

  it("explains the first cause and lists every other one", () => {
    // WHY: a run paused for several reasons needs each one cleared before it resumes.
    const causes: PauseCause[] = [
      { reason: "plan_limit", detail: "", subject: "implement||a4:2:0" },
      { reason: "budget", detail: "", subject: "" },
      { reason: "drift", detail: "anchor_archived", subject: "" },
    ];
    renderBanner("plan_limit", pausedView({ causes }));
    const banner = screen.getByRole("region", { name: "Paused: plan limit" });
    expect(banner).toHaveTextContent(`${PAUSE_MESSAGES.plan_limit} Coral retries periodically.`);
    expect(items()).toEqual([
      PAUSE_MESSAGES.budget,
      "The run’s session was archived. Unarchive it to continue, or cancel.",
    ]);
  });

  it("lists each cause once, even when two read alike", () => {
    // WHY: two refused-call causes on different steps say the same thing.
    const causes: PauseCause[] = [
      { reason: "budget", detail: "", subject: "" },
      { reason: "rejected_calls", detail: "", subject: "a" },
      { reason: "rejected_calls", detail: "", subject: "b" },
    ];
    renderBanner("budget", pausedView({ causes }));
    expect(items()).toEqual([PAUSE_MESSAGES.rejected_calls]);
  });

  it("names a step someone typed into and a step whose session changed", () => {
    // WHY: those steps need the owner's attention before the run can go on.
    const slots = [
      { ...OPEN_VIEW.slots[0]!, pending_input: true },
      { ...OPEN_VIEW.slots[1]!, drift: true },
    ];
    renderBanner("user", pausedView({ slots }));
    expect(items()).toEqual([
      `Someone typed into ${isolated("Implement")}’s session.`,
      `${isolated("Implement")}’s session was changed outside Coral.`,
    ]);
  });

  it("says a typed-into step once when a cause already names its slot", () => {
    // WHY: the cause's sentence and the slot's flag describe the same event.
    const slot = OPEN_VIEW.slots[1]!;
    const cause: PauseCause = { reason: "drift", detail: "pending_input", subject: slot.id };
    const slots = [
      { ...OPEN_VIEW.slots[0]!, pending_input: true },
      { ...slot, pending_input: true },
    ];
    renderBanner("drift", pausedView({ causes: [USER_CAUSE, cause], slots }));
    expect(items()).toEqual([
      `Someone typed into ${isolated("Implement")}’s session while Coral was finishing it.`,
      `Someone typed into ${isolated("Implement")}’s session.`,
    ]);
  });

  it("names the decisions the orchestrator still has to make", () => {
    // WHY: an open decision is the run waiting on its orchestrator, not stuck.
    renderBanner("user", pausedView({ open_decisions: ["choose||", "pick||x|0"] }));
    expect(items()).toEqual([
      `Waiting for the orchestrator to choose at ${isolated("Choose path")}.`,
      `Waiting for the orchestrator to choose at ${isolated("pick")}.`,
    ]);
  });

  it("speaks of a step plainly while the graph has not loaded", () => {
    // WHY: step names come only from the graph; the banner never shows a slot id.
    const slots = [{ ...OPEN_VIEW.slots[0]!, pending_input: true }];
    renderBanner("user", pausedView({ slots }), null);
    expect(items()).toEqual(["Someone typed into a step’s session."]);
  });

  it("explains a pause by the run's reason when the view has no causes", () => {
    // WHY: a paused header can arrive before the view that carries its causes.
    renderBanner("infra", null);
    const banner = screen.getByRole("region", { name: "Paused: infrastructure" });
    expect(banner).toHaveTextContent(PAUSE_MESSAGES.infra);
  });

  it("says only Paused for a reason this client cannot name", () => {
    // WHY: a newer server's reason must not show as a raw code.
    renderBanner("solar_flare", pausedView({ causes: [] }));
    expect(screen.getByRole("region", { name: "Paused" })).toHaveTextContent("The run paused.");
  });
});

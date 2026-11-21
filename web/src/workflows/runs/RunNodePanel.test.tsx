import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { CompiledGraph, SlotOut } from "../api/generated/coralApi";
import { runOverlay } from "../canvas/runOverlay";
import { CONTRACT_DETAIL_GATE_PASS2, CONTRACT_GRAPH } from "../fixtures/runViewContract";
import { runPath } from "../nav/coralPaths";
import { stepSessions } from "./agents/stepSessions";
import { RunNodePanel } from "./RunNodePanel";

const OVERLAY = runOverlay(CONTRACT_GRAPH, CONTRACT_DETAIL_GATE_PASS2.view);

describe("RunNodePanel", () => {
  it("shows the selected step: its kind, state, pass, goal, checks and agents", () => {
    // WHY: selecting a step shows what it does and who works on it, without a transcript.
    const graph: CompiledGraph = {
      ...CONTRACT_GRAPH,
      nodes: CONTRACT_GRAPH.nodes.map((node) =>
        node.id === "implement"
          ? { ...node, harness: "claude-native", roster: ["implementer", "implementer"] }
          : node,
      ),
    };
    render(<RunNodePanel graph={graph} nodeId="implement" overlay={OVERLAY.get("implement")!} />);
    const panel = screen.getByRole("region", { name: "Implement" });
    expect(panel).toHaveAttribute("data-node-id", "implement");
    expect(within(panel).getByTestId("run-node-state")).toHaveTextContent(
      "Step · Completed · pass 2 of 2",
    );
    expect(panel).toHaveTextContent("Implement the change");
    expect(within(panel).getByRole("list", { name: "Evidence checks" })).toHaveTextContent(
      "pytest -q",
    );
    // Two agents of one profile are two chips.
    expect(
      within(panel)
        .getAllByTestId("roster-chip")
        .map((element) => element.textContent),
    ).toEqual(["implementer · Claude Code", "implementer · Claude Code"]);
  });

  it("shows the step's name, goal and evidence commands as text", () => {
    // WHY: all three come from the workflow's YAML; none of it is rendered as HTML.
    const hostile = "Impl‮ement <img src=x onerror=alert(1)>";
    const command = "pytest -q <script>alert(1)</script>";
    const graph: CompiledGraph = {
      ...CONTRACT_GRAPH,
      nodes: CONTRACT_GRAPH.nodes.map((node) =>
        node.id === "implement"
          ? {
              ...node,
              name: hostile,
              goal: `Fix it\n<b>${hostile}</b>`,
              evidence: {
                ...node.evidence!,
                items: [{ ...node.evidence!.items[0]!, run: command }],
              },
            }
          : node,
      ),
    };
    render(<RunNodePanel graph={graph} nodeId="implement" overlay={OVERLAY.get("implement")!} />);
    const panel = screen.getByRole("region", { name: hostile });
    expect(within(panel).getByRole("heading", { level: 2 }).textContent).toBe(hostile);
    expect(
      within(panel).getByText(
        (_content, element) => element?.textContent === `Fix it\n<b>${hostile}</b>`,
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByRole("list", { name: "Evidence checks" }).textContent).toBe(command);
    expect(panel.querySelector("img, b, script")).toBeNull();
  });

  it("shows a gate's question and open state, with no checks or agents of its own", () => {
    // WHY: a gate is the owner's step; its panel says what it asks.
    render(
      <RunNodePanel
        graph={CONTRACT_GRAPH}
        nodeId="approve_change"
        overlay={OVERLAY.get("approve_change")!}
      />,
    );
    const panel = screen.getByRole("region", { name: "Approve change" });
    expect(within(panel).getByTestId("run-node-state")).toHaveTextContent(
      "Gate · Waiting for you · pass 2 of 2",
    );
    expect(panel).toHaveTextContent("Approve the change?");
    expect(within(panel).queryByRole("list", { name: "Evidence checks" })).toBeNull();
    expect(within(panel).queryByTestId("roster-chip")).toBeNull();
  });

  it("links each of the step's sessions to its transcript, latest pass first", () => {
    // WHY: a step's agents are where its transcript is read; each pass has its own session.
    const detail = CONTRACT_DETAIL_GATE_PASS2;
    const [pass1, pass2] = ["implement||a4:1:0", "implement||a4:2:0"].map(
      (id) => detail.slots.find((slot) => slot.engine_slot_id === id)!.session_id!,
    );
    render(
      <MemoryRouter>
        <RunNodePanel
          graph={CONTRACT_GRAPH}
          nodeId="implement"
          overlay={OVERLAY.get("implement")!}
          runId={detail.run_id}
          sessions={stepSessions(detail, CONTRACT_GRAPH, "implement")}
          openSessionId={pass2!}
        />
      </MemoryRouter>,
    );
    const panel = screen.getByRole("region", { name: "Implement" });
    const passes = within(panel).getAllByRole("list", { name: /^Pass / });
    expect(passes.map((list) => list.getAttribute("aria-label"))).toEqual(["Pass 2", "Pass 1"]);
    const links = passes.map((list) => within(list).getByRole("link", { name: /implementer/ }));
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      runPath(detail.run_id, { node: "implement", agent: pass2 }),
      runPath(detail.run_id, { node: "implement", agent: pass1 }),
    ]);
    expect(links[0]).toHaveAttribute("aria-current", "true");
    expect(links[1]).not.toHaveAttribute("aria-current");
  });

  it("shows an agent whose session does not exist yet without a link", () => {
    const detail = CONTRACT_DETAIL_GATE_PASS2;
    const pending: SlotOut = {
      ...detail.slots[0]!,
      engine_slot_id: "implement||a4:2:0",
      session_id: null,
      status: "pending",
    };
    render(
      <MemoryRouter>
        <RunNodePanel
          graph={CONTRACT_GRAPH}
          nodeId="implement"
          overlay={OVERLAY.get("implement")!}
          runId={detail.run_id}
          sessions={stepSessions({ ...detail, slots: [pending] }, CONTRACT_GRAPH, "implement")}
          openSessionId={null}
        />
      </MemoryRouter>,
    );
    const panel = screen.getByRole("region", { name: "Implement" });
    expect(within(panel).getByTestId("roster-chip")).toHaveTextContent("implementer");
    expect(within(panel).queryByRole("link")).toBeNull();
  });
});

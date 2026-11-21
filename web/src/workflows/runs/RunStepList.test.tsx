import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { CompiledGraph, RunView } from "../api/generated/coralApi";
import { runOverlay } from "../canvas/runOverlay";
import {
  CONTRACT_DETAIL_GATE_PASS1,
  CONTRACT_DETAIL_GATE_PASS2,
  CONTRACT_GRAPH,
} from "../fixtures/runViewContract";
import { isolated, PAUSE_MESSAGES } from "../shared/pauseCopy";
import { RunStepList } from "./RunStepList";

function renderList(view: RunView | null, selectedNodeId: string | null = null) {
  const onSelectNode = vi.fn();
  render(
    <RunStepList
      graph={CONTRACT_GRAPH}
      overlay={runOverlay(CONTRACT_GRAPH, view)}
      selectedNodeId={selectedNodeId}
      onSelectNode={onSelectNode}
    />,
  );
  return onSelectNode;
}

const item = (nodeId: string) =>
  screen.getAllByRole("listitem").find((element) => element.dataset.nodeId === nodeId)!;
const stepButton = (nodeId: string) => within(item(nodeId)).getByRole("button");

describe("RunStepList", () => {
  it("lists every node in graph order as a button with its status, pass and evidence", () => {
    // WHY: the canvas's state is readable and reachable without seeing the canvas.
    renderList(CONTRACT_DETAIL_GATE_PASS1.view);
    const list = screen.getByRole("region", { name: "Steps" });
    const items = within(list)
      .getAllByRole("listitem")
      .filter((element) => element.dataset.nodeId !== undefined);
    expect(items.map((element) => element.dataset.nodeId)).toEqual([
      "start",
      "implement",
      "approve_change",
      "end",
    ]);
    expect(items.map((element) => element.dataset.state)).toEqual([
      "completed",
      "completed",
      "running",
      "idle",
    ]);
    expect(stepButton("implement")).toHaveTextContent("Implement");
    expect(within(item("implement")).getByTestId("run-step-status")).toHaveTextContent("Completed");
    expect(within(item("implement")).getByTestId("run-step-pass")).toHaveTextContent("pass 1 of 2");
    expect(within(stepButton("implement")).getByText("Evidence checks")).toBeInTheDocument();
    expect(within(stepButton("approve_change")).queryByText("Evidence checks")).toBeNull();
    expect(within(item("end")).getByTestId("run-step-status")).toHaveTextContent("Not started");
    expect(within(item("end")).queryByTestId("run-step-pass")).toBeNull();
  });

  it("says Waiting for you on the open gate", () => {
    // WHY: the step list names what the owner has to do.
    renderList(CONTRACT_DETAIL_GATE_PASS2.view);
    expect(item("approve_change")).toHaveAttribute("data-gate-open", "true");
    expect(within(item("approve_change")).getByTestId("run-step-status")).toHaveTextContent(
      "Waiting for you",
    );
    expect(within(item("approve_change")).getByTestId("run-step-pass")).toHaveTextContent(
      "pass 2 of 2",
    );
    expect(item("implement")).not.toHaveAttribute("data-gate-open");
  });

  it("lists each step's stalls: typed into, changed, a decision to make, and its causes", () => {
    // WHY: what a paused run waits on is shown at the step that holds it.
    const view: RunView = {
      ...CONTRACT_DETAIL_GATE_PASS2.view!,
      status: "paused",
      causes: [
        { reason: "budget", detail: "activation_cap", subject: "approve_change" },
        { reason: "user", detail: "user", subject: "" },
      ],
      slots: [
        { id: "implement||a4:1:0", status: "closed", pending_input: true, drift: true },
        { id: "implement||a4:2:0", status: "closed", pending_input: true, drift: false },
      ],
      open_decisions: ["approve_change||a4:2"],
    };
    renderList(view);
    const stalls = (nodeId: string) =>
      within(item(nodeId))
        .queryAllByTestId("run-step-stall")
        .map((element) => element.textContent);
    expect(stalls("implement")).toEqual([
      "Someone typed into this step’s session.",
      "This step’s session was changed outside Coral.",
    ]);
    expect(stalls("approve_change")).toEqual([
      "Waiting for the orchestrator to choose.",
      PAUSE_MESSAGES.budget,
    ]);
    expect(stalls("start")).toEqual([]);
  });

  it("says a typed-into step once when its cause already says so", () => {
    // WHY: the cause's copy names the same event in longer words.
    const view: RunView = {
      ...CONTRACT_DETAIL_GATE_PASS2.view!,
      status: "paused",
      causes: [{ reason: "drift", detail: "pending_input", subject: "implement||a4:2:0" }],
      slots: [{ id: "implement||a4:2:0", status: "closing", pending_input: true, drift: false }],
    };
    renderList(view);
    expect(
      within(item("implement"))
        .getAllByTestId("run-step-stall")
        .map((element) => element.textContent),
    ).toEqual([
      `Someone typed into ${isolated("Implement")}’s session while Coral was finishing it.`,
    ]);
  });

  it("selects steps from the keyboard alone, one tab stop per step in graph order", async () => {
    // WHY: the list is the canvas's keyboard path; its stall lines take no focus.
    const view: RunView = {
      ...CONTRACT_DETAIL_GATE_PASS2.view!,
      slots: [{ id: "implement||a4:2:0", status: "closed", pending_input: true, drift: true }],
    };
    const onSelectNode = renderList(view);
    const user = userEvent.setup();
    const stops: (string | undefined)[] = [];
    for (let stop = 0; stop < CONTRACT_GRAPH.nodes.length; stop += 1) {
      // eslint-disable-next-line no-await-in-loop -- each Tab moves on from the last stop
      await user.tab();
      stops.push(document.activeElement?.closest("li")?.dataset.nodeId);
    }
    expect(stops).toEqual(["start", "implement", "approve_change", "end"]);
    await user.keyboard("{Enter}");
    expect(onSelectNode).toHaveBeenLastCalledWith("end");
    await user.tab({ shift: true });
    await user.keyboard(" ");
    expect(onSelectNode).toHaveBeenLastCalledWith("approve_change");
    expect(onSelectNode).toHaveBeenCalledTimes(2);
  });

  it("shows step names and the stall copy built from them as text", () => {
    // WHY: a step's name comes from the workflow's YAML; markup and bidi marks stay characters.
    const hostile = "Impl‮ement <img src=x onerror=alert(1)> <b>b</b>";
    const graph: CompiledGraph = {
      ...CONTRACT_GRAPH,
      nodes: CONTRACT_GRAPH.nodes.map((node) =>
        node.id === "implement" ? { ...node, name: hostile } : node,
      ),
    };
    const view: RunView = {
      ...CONTRACT_DETAIL_GATE_PASS2.view!,
      status: "paused",
      causes: [{ reason: "drift", detail: "post_close", subject: "implement||a4:2:0" }],
    };
    render(
      <RunStepList
        graph={graph}
        overlay={runOverlay(graph, view)}
        selectedNodeId={null}
        onSelectNode={() => {}}
      />,
    );
    expect(within(stepButton("implement")).getByText(hostile)).toBeInTheDocument();
    expect(within(item("implement")).getByTestId("run-step-stall").textContent).toBe(
      `${isolated(hostile)}’s session kept working after its step closed.`,
    );
    expect(screen.getByRole("region", { name: "Steps" }).querySelector("img, b")).toBeNull();
  });

  it("marks the selected step and selects the one pressed", () => {
    // WHY: pressing a step opens its details, as clicking its node does.
    const onSelectNode = renderList(CONTRACT_DETAIL_GATE_PASS1.view, "implement");
    expect(stepButton("implement")).toHaveAttribute("aria-current", "true");
    expect(stepButton("approve_change")).not.toHaveAttribute("aria-current");
    fireEvent.click(stepButton("approve_change"));
    expect(onSelectNode).toHaveBeenCalledWith("approve_change");
  });
});

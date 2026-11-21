import { cleanup, render, screen } from "@testing-library/react";
import { HandIcon } from "lucide-react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { runViewCardUi } from "./gateCardUi";

afterEach(cleanup);

describe("runViewCardUi", () => {
  const { InboxCard, KindTile, InboxActions } = runViewCardUi;

  it("always shows a card's body, with no toggle", () => {
    // WHY: on the run page a gate card is the thing to act on, so it never collapses.
    const onToggle = vi.fn();
    render(
      <InboxCard
        testId="run-gate"
        dataKind="workflow-gate"
        tile={<KindTile icon={HandIcon} tone="yellow" />}
        kindLabel="Workflow gate"
        title="Ship the bridge"
        preview="Approve change"
        at={1_767_268_920}
        unread
        expanded={false}
        onToggle={onToggle}
      >
        <p>Approve the change?</p>
      </InboxCard>,
    );
    const card = screen.getByRole("region", { name: "Workflow gate: Approve change" });
    expect(card).toHaveAttribute("data-testid", "run-gate");
    expect(card).toHaveAttribute("data-kind", "workflow-gate");
    expect(screen.getByText("Approve the change?")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(onToggle).not.toHaveBeenCalled();
  });

  it("names a card by its kind alone when it has no preview", () => {
    // WHY: the heading still says what the card is.
    render(
      <InboxCard
        testId="run-card"
        tile={null}
        kindLabel="Run paused"
        title="Ship the bridge"
        preview={null}
        at={0}
        unread={false}
        expanded
        onToggle={() => {}}
      >
        body
      </InboxCard>,
    );
    expect(screen.getByRole("region", { name: "Run paused" })).toBeInTheDocument();
  });

  it("renders the tile's tone and an action row", () => {
    // WHY: the tile colour matches the Inbox's, and actions keep their order.
    render(
      <InboxActions>
        <KindTile icon={HandIcon} tone="red" />
        <button type="button">First</button>
        <button type="button">Second</button>
      </InboxActions>,
    );
    expect(screen.getByTestId("run-card-tile")).toHaveAttribute("data-tone", "red");
    expect(screen.getAllByRole("button").map((button) => button.textContent)).toEqual([
      "First",
      "Second",
    ]);
  });
});

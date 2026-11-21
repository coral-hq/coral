import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RosterChip } from "./RosterChip";

describe("RosterChip", () => {
  it("names the roster profile and the agent that runs it", () => {
    // WHY: a step's chip says who works on it.
    render(<RosterChip profile="implementer" harness="claude-sdk" />);
    expect(screen.getByTestId("roster-chip")).toHaveTextContent("implementer · Claude");
  });

  it("names only the profile when the step uses the default agent", () => {
    // WHY: a node without a harness runs on the workspace default, which the graph does not name.
    render(<RosterChip profile="reviewer" harness={null} />);
    expect(screen.getByTestId("roster-chip")).toHaveTextContent(/^reviewer$/);
  });
});

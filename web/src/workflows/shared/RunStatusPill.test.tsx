import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RunStatusPill } from "./RunStatusPill";

describe("RunStatusPill", () => {
  it("shows the status text with its kind and tone", () => {
    // WHY: views and tests tell "Needs you" from "Running" by the pill alone.
    render(<RunStatusPill status="running" pauseReason={null} openGates={["approve||:1"]} />);
    const pill = screen.getByText("Needs you");
    expect(pill).toHaveAttribute("data-status", "needs_you");
    expect(pill).toHaveClass("text-status-yellow");
  });

  it("names a paused run's reason", () => {
    // WHY: the pill says why the run stopped without opening the banner.
    render(<RunStatusPill status="paused" pauseReason="plan_limit" openGates={null} />);
    expect(screen.getByText("Paused: plan limit")).toHaveAttribute("data-status", "paused");
  });
});

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CapabilityChips, UsedBy } from "./CapabilityChips";

afterEach(cleanup);

describe("CapabilityChips", () => {
  it("names every capability with its support, never showing unknown as supported", () => {
    render(
      <CapabilityChips
        capabilities={{
          tool_gating: "supported",
          fs_read_only: "unsupported",
          steering: "unknown",
          usage_reporting: "unknown",
        }}
      />,
    );
    const chips = screen.getAllByRole("listitem");
    expect(chips.map((chip) => [chip.textContent, chip.dataset.support])).toEqual([
      ["tool gating: supported", "supported"],
      ["read-only files: unsupported", "unsupported"],
      ["steering: unknown", "unknown"],
      ["usage reporting: unknown", "unknown"],
    ]);
  });

  it("counts workflows and running runs", () => {
    render(<UsedBy usedBy={{ workflows: 2, running_runs: 0 }} />);
    expect(screen.getByText("Used by 2 workflows, 0 running runs")).toBeInTheDocument();
  });
});

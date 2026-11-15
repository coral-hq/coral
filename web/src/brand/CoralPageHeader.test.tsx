import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { CoralPageHeader } from "./CoralPageHeader";

afterEach(cleanup);

describe("CoralPageHeader", () => {
  it("renders the title as the h1 with a decorative accent rail", () => {
    render(<CoralPageHeader title="Workflows" description="Run agent workflows." />);

    expect(screen.getByRole("heading", { level: 1, name: "Workflows" })).toHaveClass(
      "font-display",
    );
    expect(screen.getByText("Run agent workflows.")).toBeInTheDocument();
    expect(screen.getByTestId("accent-rail")).toHaveAttribute("aria-hidden", "true");
  });

  it("passes actions and the title accessory through", () => {
    render(
      <CoralPageHeader
        title="Inbox"
        titleAccessory={<span data-testid="count">3</span>}
        actions={<button type="button">New</button>}
      />,
    );

    expect(screen.getByTestId("count")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New" }).parentElement).toHaveClass("flex-wrap");
  });

  it("omits the description and actions when absent", () => {
    const { container } = render(<CoralPageHeader title="Profiles" />);

    expect(container.querySelector("p")).toBeNull();
    expect(container.querySelector("header")!.children).toHaveLength(1);
  });

  it("uses the shell heading clearance only for the fullBleed variant", () => {
    const { container, rerender } = render(<CoralPageHeader title="A" />);
    expect(container.querySelector("header")).not.toHaveClass("canvas-page-heading");

    rerender(<CoralPageHeader title="A" variant="fullBleed" />);
    expect(container.querySelector("header")).toHaveClass("canvas-page-heading");
  });
});

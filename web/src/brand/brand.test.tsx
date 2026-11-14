/// <reference types="node" />
// Node types via explicit reference: the app tsconfig is browser-only.
import { readFileSync } from "node:fs";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/BrandLogo", () => ({
  BrandLogo: ({ className, variant }: { className?: string; variant?: string }) => (
    <span data-testid="brand-logo" data-variant={variant} className={className} />
  ),
}));

import { CORAL_MARK_PATHS, CoralMark } from "./CoralMark";
import { CoralHero } from "./CoralHero";
import { CoralWordmark } from "./CoralWordmark";
import { CORAL_URL_SCHEME } from "./urlScheme";

// Relative to the vitest root (web/).
const markAssetSource = readFileSync("src/brand/assets/coral-mark.svg", "utf8");
// Static copies served outside the bundle (favicon); they must stay byte-identical.
const MARK_COPIES = ["public/coral-mark.svg"];

afterEach(cleanup);

describe("CoralMark", () => {
  it("draws the Clay mosaic and leaf on a transparent ground, hidden from assistive tech", () => {
    const { container } = render(<CoralMark className="size-7" />);
    const svg = container.querySelector("svg")!;

    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(svg).toHaveAttribute("viewBox", "0 0 64 64");
    expect(svg).toHaveClass("coral-mark", "size-7");
    expect(svg.querySelector("rect")).toBeNull();
    expect([...svg.querySelectorAll("path")].map((path) => path.getAttribute("fill"))).toEqual([
      "#4D7356",
      "#9EAB92",
      "#B9CDB0",
      "#C19A55",
      "#864A31",
      "#6E2B22",
      "#4D7356",
    ]);
  });

  it("matches the static placeholder asset used outside React", () => {
    expect(markAssetSource).toContain("Placeholder Coral mark");
    for (const path of CORAL_MARK_PATHS) {
      expect(markAssetSource).toContain(`<path d="${path.d}" fill="${path.fill}"/>`);
    }
    expect(markAssetSource.match(/<path /g)).toHaveLength(CORAL_MARK_PATHS.length);
  });

  it.each(MARK_COPIES)("keeps the %s copy identical to the asset", (copy) => {
    expect(readFileSync(copy, "utf8")).toBe(markAssetSource);
  });
});

describe("CORAL_URL_SCHEME", () => {
  it("matches the scheme the desktop shell registers and checks", () => {
    const desktopBrand = readFileSync("electron/src/brand.js", "utf8");
    expect(CORAL_URL_SCHEME).toBe("coral");
    expect(desktopBrand).toContain(`const URL_SCHEME = "${CORAL_URL_SCHEME}";`);
  });
});

describe("CoralWordmark", () => {
  it("sets 'Coral' in the display face beside the mark on one row", () => {
    render(<CoralWordmark data-testid="wordmark" />);
    const wordmark = screen.getByTestId("wordmark");

    expect(wordmark).toHaveClass("inline-flex", "items-center");
    expect(wordmark.querySelector("svg.coral-mark")).not.toBeNull();
    expect(screen.getByText("Coral")).toHaveClass("font-display", "font-medium", "leading-none");
  });

  it("keeps the layout for another name", () => {
    render(<CoralWordmark name="Acme" />);

    expect(screen.getByText("Acme")).toHaveClass("font-display");
  });
});

describe("CoralHero", () => {
  it("puts the brand mark beside the display heading at the heading's height", () => {
    render(<CoralHero heading="Direct the run…" />);

    const heading = screen.getByRole("heading", { level: 1, name: "Direct the run…" });
    expect(heading).toHaveClass("font-display", "font-medium");
    expect(screen.getByTestId("brand-logo")).toHaveAttribute("data-variant", "eyes");
    expect(screen.getByTestId("brand-logo")).toHaveClass("h-[1em]");
    expect(screen.getByTestId("coral-hero")).toHaveClass("flex", "items-center");
  });

  it("shows only the mark for an empty operator heading", () => {
    render(<CoralHero heading="" />);

    expect(screen.queryByRole("heading")).toBeNull();
    expect(screen.getByTestId("brand-logo")).toBeInTheDocument();
  });
});

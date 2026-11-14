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

import { CoralMark } from "./CoralMark";
import { CoralHero } from "./CoralHero";
import { CoralWordmark } from "./CoralWordmark";
import { CORAL_URL_SCHEME } from "./urlScheme";

afterEach(cleanup);

describe("CoralMark", () => {
  it("shows the Coral logo image, hidden from assistive tech", () => {
    const { container } = render(<CoralMark className="size-7" />);
    const image = container.querySelector("img")!;

    expect(image.getAttribute("src")).toMatch(/coral-logo\.png$/);
    expect(image).toHaveAttribute("alt", "");
    expect(image).toHaveAttribute("aria-hidden", "true");
    expect(image).toHaveClass("coral-mark", "aspect-square", "object-contain", "size-7");
  });

  it("is the favicon the web UI serves", () => {
    // Relative to the vitest root (web/).
    const indexHtml = readFileSync("index.html", "utf8");
    expect(indexHtml).toContain('href="%BASE_URL%coral-favicon.png"');
    expect(readFileSync("public/coral-favicon.png").subarray(1, 4).toString()).toBe("PNG");
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
    expect(wordmark.querySelector("img.coral-mark")).not.toBeNull();
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

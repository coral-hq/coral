/// <reference types="node" />
// Node types via explicit reference: the app tsconfig is browser-only, and
// importing coral.css?raw instead yields "" under vitest's CSS stubbing.
import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it } from "vitest";

// Relative to the vitest root (web/).
const coralCssSource = readFileSync("src/brand/coral.css", "utf8");
const indexCssSource = readFileSync("src/index.css", "utf8");
const generatedPaletteCssSource = readFileSync("src/themePalettes.generated.css", "utf8");

const LIGHT_DEFAULT = ":root:not(.dark):not([data-theme])";
const DARK_DEFAULT = ".dark:not([data-theme])";

/** Removes `@media`/`@keyframes` blocks, whose nested braces the rule scan can't follow. */
function withoutAtRules(source: string): string {
  let result = "";
  let index = 0;
  while (index < source.length) {
    const at = source.indexOf("@", index);
    if (at === -1) return result + source.slice(index);
    result += source.slice(index, at);
    let depth = 0;
    let cursor = source.indexOf("{", at);
    do {
      if (source[cursor] === "{") depth += 1;
      if (source[cursor] === "}") depth -= 1;
      cursor += 1;
    } while (depth > 0 && cursor < source.length);
    index = cursor;
  }
  return result;
}

/** `selector { body }` rules outside at-rules, with comments stripped. */
function topLevelRules(source: string): Map<string, string> {
  const flat = withoutAtRules(source.replace(/\/\*[\s\S]*?\*\//g, ""));
  const rules = new Map<string, string>();
  for (const [, selector, body] of flat.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    rules.set(selector.trim(), body);
  }
  return rules;
}

function declaration(body: string | undefined, name: string): string | undefined {
  return body?.match(new RegExp(`(?:^|;|\\s)${name}:\\s*([^;]+);`))?.[1].trim();
}

const rules = topLevelRules(coralCssSource);

afterEach(() => {
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.classList.remove("dark");
});

describe("coral.css", () => {
  it("is imported by index.css after the generated palettes", () => {
    const paletteImport = indexCssSource.indexOf('@import "./themePalettes.generated.css";');
    const coralImport = indexCssSource.indexOf('@import "./brand/coral.css";');
    expect(paletteImport).toBeGreaterThan(-1);
    expect(coralImport).toBeGreaterThan(paletteImport);
  });

  it("scopes its remaps to the default palette with the generated omni selectors", () => {
    expect(generatedPaletteCssSource).toContain(`${LIGHT_DEFAULT} {`);
    expect(generatedPaletteCssSource).toContain(`${DARK_DEFAULT} {`);
    const remapSelectors = [...rules.keys()].filter(
      (selector) =>
        selector !== ":root" && selector !== ".dark" && !selector.startsWith(".coral-mark"),
    );
    expect(remapSelectors.length).toBeGreaterThan(0);
    for (const selector of remapSelectors) {
      expect(
        selector.startsWith(LIGHT_DEFAULT) || selector.startsWith(DARK_DEFAULT),
        selector,
      ).toBe(true);
    }
  });

  it("applies to the stored omni palette but never to another palette", () => {
    const root = document.documentElement;
    expect(root.matches(LIGHT_DEFAULT)).toBe(true);
    root.classList.add("dark");
    expect(root.matches(DARK_DEFAULT)).toBe(true);
    root.setAttribute("data-theme", "github");
    expect(root.matches(DARK_DEFAULT)).toBe(false);
    root.classList.remove("dark");
    expect(root.matches(LIGHT_DEFAULT)).toBe(false);
  });

  it("remaps status, chart, tag and CTA tokens onto the Clay Score ramp", () => {
    const light = rules.get(LIGHT_DEFAULT);
    const dark = rules.get(DARK_DEFAULT);
    expect(declaration(rules.get(":root"), "--coral-forest")).toBe("#4d7356");
    expect(declaration(rules.get(":root"), "--coral-clay")).toBe("#864a31");
    for (const body of [light, dark]) {
      expect(declaration(body, "--success")).toBe("var(--coral-forest)");
      expect(declaration(body, "--warning")).toBe("var(--coral-mustard)");
      expect(declaration(body, "--info")).toBe("var(--coral-sage)");
      expect(declaration(body, "--chart-1")).toBe("var(--coral-forest)");
      expect(declaration(body, "--chart-5")).toBe("var(--coral-ink)");
    }
    expect(declaration(light, "--tag-pink")).toBe("rgba(134, 74, 49, 0.08)");
    expect(declaration(light, "--primary-cta")).toBe("var(--coral-clay)");
    expect(declaration(dark, "--primary-cta")).toBe("var(--coral-mustard)");
    expect(declaration(rules.get(`${LIGHT_DEFAULT} .slash-skill-icon`), "color")).toBe(
      "var(--brand-accent)",
    );
  });

  it("keeps true destructive red", () => {
    expect(coralCssSource).not.toMatch(/--destructive\s*:/);
    expect(coralCssSource).not.toMatch(/--status-red\s*:/);
  });

  it("pulses the working mark and stops for reduced motion", () => {
    expect(declaration(rules.get(".coral-mark.otto-working"), "animation")).toMatch(
      /^coral-mark-pulse /,
    );
    expect(coralCssSource).toMatch(
      /@media \(prefers-reduced-motion: reduce\)\s*\{\s*\.coral-mark\.otto-working\s*\{\s*animation: none;/,
    );
  });
});

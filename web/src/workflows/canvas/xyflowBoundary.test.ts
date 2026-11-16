import { describe, expect, it } from "vitest";

const sources = import.meta.glob("/src/workflows/**/*.{ts,tsx}", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

describe("xyflow boundary", () => {
  it("is imported only under workflows/canvas", () => {
    const offenders = Object.entries(sources)
      .filter(([path]) => !path.startsWith("/src/workflows/canvas/") && !path.endsWith(".test.ts"))
      .filter(([path]) => !path.endsWith(".test.tsx"))
      .filter(([, source]) => /from\s+["']@xyflow\/react|import\s+["']@xyflow\/react/.test(source))
      .map(([path]) => path);
    expect(offenders).toEqual([]);
    expect(Object.keys(sources).some((path) => path.startsWith("/src/workflows/canvas/"))).toBe(
      true,
    );
  });
});

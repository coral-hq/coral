import { afterEach, describe, expect, it } from "vitest";
import { VIEW_PATCH_CASES } from "../fixtures/runViewContract";
import {
  applyViewPatch,
  MAX_PATCH_OPS,
  ViewPatchError,
  type JsonObject,
  type JsonPatchOperation,
} from "./viewPatch";

/**
 * A JSON text of `value` with sorted keys. It reads own `__proto__` members as data, where
 * deep equality helpers may not.
 */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, unknown>;
    const members = Object.keys(record)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(record[key])}`);
    return `{${members.join(",")}}`;
  }
  return JSON.stringify(value);
}

const VIEW: JsonObject = { status: "running", items: ["a", "b"], rows: [{ id: "r1" }] };

// Each prototype token as an own member at the root and inside an array's element, so only
// the token rule can refuse a path through it.
const OWN_PROTOTYPE_MEMBERS = JSON.parse(
  '{"__proto__":{"x":1},"constructor":{"x":1},"prototype":{"x":1},' +
    '"rows":[{"id":"r1","__proto__":{"x":1},"constructor":{"x":1},"prototype":{"x":1}}]}',
) as JsonObject;

afterEach(() => {
  // No case may reach a shared prototype.
  expect(({} as Record<string, unknown>).polluted).toBeUndefined();
  expect(({} as Record<string, unknown>).x).toBeUndefined();
});

describe("applyViewPatch, against apply_view_patch", () => {
  it("has the cases the contract promises", () => {
    expect(VIEW_PATCH_CASES.filter((testCase) => testCase.client_error)).toHaveLength(9);
    expect(VIEW_PATCH_CASES.some((testCase) => testCase.name.startsWith("live entry"))).toBe(true);
  });

  it.each(VIEW_PATCH_CASES.map((testCase) => [testCase.name, testCase] as const))(
    "%s",
    (_name, testCase) => {
      const view = testCase.view as JsonObject;
      const before = canonical(view);
      const apply = () => applyViewPatch(view, testCase.patch);
      if (testCase.error === true || testCase.client_error === true) {
        expect(apply).toThrow(ViewPatchError);
      } else {
        const result = apply();
        expect(Object.getPrototypeOf(result)).toBe(Object.prototype);
        expect(canonical(result)).toBe(canonical(testCase.result));
      }
      expect(canonical(view)).toBe(before);
    },
  );

  it("keeps a client-only refusal's own Python result, so the web is the stricter side", () => {
    for (const testCase of VIEW_PATCH_CASES.filter((item) => item.client_error)) {
      expect(testCase.result, testCase.name).toBeDefined();
    }
  });
});

describe("applyViewPatch, the web's own limits", () => {
  it(`takes ${MAX_PATCH_OPS} operations and refuses one more`, () => {
    const ops = (count: number): JsonPatchOperation[] =>
      Array.from({ length: count }, () => ({ op: "replace", path: "/status", value: "x" }));
    expect(applyViewPatch(VIEW, ops(MAX_PATCH_OPS)).status).toBe("x");
    expect(() => applyViewPatch(VIEW, ops(MAX_PATCH_OPS + 1))).toThrow(ViewPatchError);
  });

  it.each([
    ["an operation that is not an object", [null]],
    ["an operation with an extra member", [{ op: "add", path: "/x", value: 1, from: "/y" }]],
    ["a path that is not a string", [{ op: "add", path: 1, value: 1 }]],
    ["an op that is not a string", [{ op: ["add"], path: "/x", value: 1 }]],
    ["prototype as an array token", [{ op: "add", path: "/items/prototype", value: 1 }]],
    ["an inherited intermediate member", [{ op: "add", path: "/toString/x", value: 1 }]],
  ])("refuses %s", (_name, patch) => {
    expect(() => applyViewPatch(VIEW, patch as unknown as JsonPatchOperation[])).toThrow(
      ViewPatchError,
    );
  });

  it.each(
    ["__proto__", "constructor", "prototype"].flatMap((token) =>
      ["add", "replace", "remove"].flatMap((op) =>
        [`/${token}`, `/${token}/x`, `/rows/0/${token}`, `/rows/0/${token}/x`].map(
          (path) => [op, path] as const,
        ),
      ),
    ),
  )("refuses %s at %s, even where the view holds that member", (op, path) => {
    const before = canonical(OWN_PROTOTYPE_MEMBERS);
    const patch = [{ op, path, value: { polluted: true } }];
    expect(() => applyViewPatch(OWN_PROTOTYPE_MEMBERS, patch)).toThrow(ViewPatchError);
    expect(canonical(OWN_PROTOTYPE_MEMBERS)).toBe(before);
  });

  it("refuses a patch that is not an array", () => {
    expect(() => applyViewPatch(VIEW, {} as unknown as JsonPatchOperation[])).toThrow(
      ViewPatchError,
    );
  });

  it("inserts a copy of each value, never the patch's own object", () => {
    const value = { id: "r2", nested: { n: 1 } };
    const result = applyViewPatch(VIEW, [{ op: "add", path: "/rows/-", value }]);
    const rows = result.rows as JsonObject[];
    expect(rows[1]).toEqual(value);
    expect(rows[1]).not.toBe(value);
    value.nested.n = 2;
    expect((rows[1]!.nested as JsonObject).n).toBe(1);
  });

  it("copies only the containers it writes into, once per call", () => {
    const result = applyViewPatch(VIEW, [
      { op: "add", path: "/items/-", value: "c" },
      { op: "remove", path: "/items/0", value: null },
    ]);
    expect(result).not.toBe(VIEW);
    expect(result.items).toEqual(["b", "c"]);
    expect(VIEW.items).toEqual(["a", "b"]);
    expect(result.rows).toBe(VIEW.rows);
  });

  it("writes an own __proto__ member of a value as data, never as a prototype", () => {
    const value = JSON.parse('{"__proto__": {"polluted": true}}') as JsonObject;
    const result = applyViewPatch({}, [{ op: "add", path: "/x", value }]);
    const inserted = result.x as JsonObject;
    expect(Object.hasOwn(inserted, "__proto__")).toBe(true);
    expect(Object.getPrototypeOf(inserted)).toBe(Object.prototype);
    expect((inserted as Record<string, unknown>).polluted).toBeUndefined();
  });
});

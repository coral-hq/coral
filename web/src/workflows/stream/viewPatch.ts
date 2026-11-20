// Apply a run-log row's view patch: RFC 6902 `add`, `remove` and `replace` by position, as
// `coral/runview/patch.py` does, checked against the same Python-generated cases. The web is
// stricter in two ways the run view never meets: it refuses the tokens `__proto__`,
// `constructor` and `prototype`, and it caps pointers and patches.

export type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;

export interface JsonObject {
  [key: string]: JsonValue;
}

/** One operation as the stream sends it; anything else in its place is refused. */
export interface JsonPatchOperation {
  readonly op: string;
  readonly path: string;
  readonly value?: unknown;
}

export const MAX_POINTER_TOKENS = 16;
export const MAX_POINTER_CHARS = 1_024;
export const MAX_PATCH_OPS = 10_000;

/** A patch the view cannot take; the stream client reconnects for a fresh snapshot. */
export class ViewPatchError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ViewPatchError";
  }
}

type Op = "add" | "remove" | "replace";

const OPS: ReadonlySet<string> = new Set<Op>(["add", "remove", "replace"]);
const OPERATION_MEMBERS: ReadonlySet<string> = new Set(["op", "path", "value"]);
const PROTOTYPE_TOKENS: ReadonlySet<string> = new Set(["__proto__", "constructor", "prototype"]);
// At most 18 digits, as the server takes them.
const ARRAY_INDEX = /^(?:0|[1-9][0-9]{0,17})$/;
const BAD_ESCAPE = /~(?![01])/;

/**
 * A new view with `patch` applied in order; `view` and `patch` are left unchanged.
 *
 * Only the containers an operation writes into are copied (once per call), so the result
 * shares every untouched part with `view`: change neither in place.
 *
 * @throws ViewPatchError for an operation the view cannot take, or a result that is not an
 *   object.
 */
export function applyViewPatch(
  view: Readonly<JsonObject>,
  patch: readonly JsonPatchOperation[],
): JsonObject {
  if (!Array.isArray(patch)) throw new ViewPatchError("a patch is a list of operations");
  if (patch.length > MAX_PATCH_OPS) {
    throw new ViewPatchError(`a patch holds at most ${MAX_PATCH_OPS} operations`);
  }
  const copies = new Set<object>();
  let document: unknown = own(view, copies);
  for (const operation of patch) document = applyOperation(document, operation, copies);
  if (!isObject(document) || Array.isArray(document)) {
    throw new ViewPatchError("a patched view must be a JSON object");
  }
  return document as JsonObject;
}

function applyOperation(document: unknown, operation: unknown, copies: Set<object>): unknown {
  const { op, path, value } = checkedOperation(operation);
  const tokens = pointerTokens(path);
  if (tokens.length === 0) {
    if (op === "remove") throw new ViewPatchError("cannot remove the whole view");
    // The value is this call's own copy, so later operations may write into it.
    if (isObject(value)) copies.add(value);
    return value;
  }
  const root = own(document, copies);
  let parent = root;
  for (const token of tokens.slice(0, -1)) parent = writableChild(parent, token, path, copies);
  const last = tokens.at(-1)!;
  if (parent === null) throw new ViewPatchError(`${path}: the parent is null`);
  if (Array.isArray(parent)) {
    if (op === "add") {
      parent.splice(last === "-" ? parent.length : arrayIndex(last, parent.length, path), 0, value);
    } else {
      const index = arrayIndex(last, parent.length - 1, path);
      if (op === "remove") parent.splice(index, 1);
      else parent[index] = value;
    }
  } else if (isObject(parent)) {
    if (op !== "add" && !Object.hasOwn(parent, last)) {
      throw new ViewPatchError(`${path}: no such member`);
    }
    if (op === "remove") Reflect.deleteProperty(parent, last);
    else defineMember(parent, last, value);
  } else {
    throw new ViewPatchError(`${path}: the parent is not an object or an array`);
  }
  return root;
}

/** The operation's fields, with its value copied (a missing value is `null`, as on the server). */
function checkedOperation(operation: unknown): { op: Op; path: string; value: unknown } {
  if (!isObject(operation) || Array.isArray(operation)) {
    throw new ViewPatchError("an operation is an object");
  }
  const record = operation as Record<string, unknown>;
  if (Object.keys(record).some((key) => !OPERATION_MEMBERS.has(key))) {
    throw new ViewPatchError("an operation holds only op, path and value");
  }
  const { op, path } = record;
  if (typeof op !== "string" || !OPS.has(op)) throw new ViewPatchError("unknown operation");
  if (typeof path !== "string") throw new ViewPatchError("a path is a string");
  const value =
    record.value === undefined ? null : (JSON.parse(JSON.stringify(record.value)) as unknown);
  return { op: op as Op, path, value };
}

/** The reference tokens of a JSON pointer (RFC 6901); the empty pointer is the root. */
function pointerTokens(path: string): string[] {
  if (path === "") return [];
  if (path.length > MAX_POINTER_CHARS) {
    throw new ViewPatchError(`a pointer holds at most ${MAX_POINTER_CHARS} characters`);
  }
  if (!path.startsWith("/")) throw new ViewPatchError(`${path}: a pointer starts with '/'`);
  if (BAD_ESCAPE.test(path)) throw new ViewPatchError(`${path}: '~' must be followed by 0 or 1`);
  const tokens = path
    .slice(1)
    .split("/")
    .map((token) => token.replaceAll("~1", "/").replaceAll("~0", "~"));
  if (tokens.length > MAX_POINTER_TOKENS) {
    throw new ViewPatchError(`a pointer holds at most ${MAX_POINTER_TOKENS} tokens`);
  }
  if (tokens.some((token) => PROTOTYPE_TOKENS.has(token))) {
    throw new ViewPatchError(`${path}: a prototype member is never part of a run view`);
  }
  return tokens;
}

/** The container `token` names in `node`, copied into it once. */
function writableChild(node: unknown, token: string, path: string, copies: Set<object>): unknown {
  if (node === null) throw new ViewPatchError(`${path}: the parent is null`);
  if (Array.isArray(node)) {
    const index = arrayIndex(token, node.length - 1, path);
    const child = own(node[index], copies);
    node[index] = child;
    return child;
  }
  if (isObject(node)) {
    if (!Object.hasOwn(node, token)) throw new ViewPatchError(`${path}: no such member`);
    const child = own((node as Record<string, unknown>)[token], copies);
    defineMember(node, token, child);
    return child;
  }
  throw new ViewPatchError(`${path}: the parent is not an object or an array`);
}

/** `node` itself when this call already copied it or it is a scalar; else a shallow copy. */
function own(node: unknown, copies: Set<object>): unknown {
  if (!isObject(node) || copies.has(node)) return node;
  const copy: object = Array.isArray(node) ? node.slice() : { ...node };
  copies.add(copy);
  return copy;
}

function arrayIndex(token: string, highest: number, path: string): number {
  if (!ARRAY_INDEX.test(token) || Number(token) > highest) {
    throw new ViewPatchError(`${path}: no such array index`);
  }
  return Number(token);
}

/** Write a member as data, so a key such as `__proto__` can never reach a prototype. */
function defineMember(target: object, key: string, value: unknown): void {
  Object.defineProperty(target, key, {
    value,
    writable: true,
    enumerable: true,
    configurable: true,
  });
}

function isObject(value: unknown): value is object {
  return typeof value === "object" && value !== null;
}

import { renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as hostModule from "@/lib/host";
import { coralScope, useCoralScope } from "./viewerScope";

const viewer = vi.hoisted(() => ({ id: "alice" as string | null }));
vi.mock("@/hooks/useViewerId", () => ({ useViewerId: () => viewer.id }));
// An embedded host's identity is set once per page, so the test steers the readers instead.
const host = vi.hoisted(() => ({ server: undefined as string | null | undefined, generation: 0 }));
vi.mock("@/lib/host", async (importActual) => {
  const actual = await importActual<typeof hostModule>();
  return {
    ...actual,
    getOmnigentServerIdentity: () =>
      host.server === undefined ? actual.getOmnigentServerIdentity() : host.server,
    getOmnigentHostGeneration: () => host.generation,
  };
});

const wrapper = ({ children }: { children: ReactNode }) =>
  createElement(MemoryRouter, null, children);

afterEach(() => {
  viewer.id = "alice";
  host.server = undefined;
  host.generation = 0;
  delete window.__OMNIGENT_BASE_PATH__;
});

describe("useCoralScope", () => {
  it("builds the scope string the Inbox built before: server, app root, viewer", () => {
    // WHY: the Inbox's cached feed and the run keys share this string; a new shape drops caches.
    const { result } = renderHook(() => useCoralScope(), { wrapper });
    expect(result.current).toEqual({
      scope: JSON.stringify([window.location.origin, "/", "alice"]),
      ready: true,
    });
  });

  it("puts the deployment's base path in the app root", () => {
    // WHY: two apps behind one origin at different paths are different servers.
    window.__OMNIGENT_BASE_PATH__ = "/proxy/6767";
    const { result } = renderHook(() => useCoralScope(), { wrapper });
    expect(result.current.scope).toBe(
      JSON.stringify([window.location.origin, "/proxy/6767/", "alice"]),
    );
  });

  it("names an embedded host's server, or its mount when the host names none", () => {
    // WHY: an embed can proxy many backends behind one origin, so the origin names none of them.
    host.server = "workspace-7";
    expect(renderHook(() => useCoralScope(), { wrapper }).result.current.scope).toBe(
      JSON.stringify(["workspace-7", "/", "alice"]),
    );
    host.server = null;
    host.generation = 3;
    expect(renderHook(() => useCoralScope(), { wrapper }).result.current.scope).toBe(
      JSON.stringify(["mount:3", "/", "alice"]),
    );
  });

  it("gives another viewer another scope", () => {
    // WHY: a sign-in as someone else must never read the last viewer's cached runs.
    const { result, rerender } = renderHook(() => useCoralScope(), { wrapper });
    const alice = result.current.scope;
    viewer.id = "bob";
    rerender();
    expect(result.current.scope).not.toBe(alice);
    expect(result.current.scope).toBe(coralScope("bob", "/"));
  });

  it("is not ready until the viewer is known", () => {
    // WHY: queries keyed before identity resolves would be filed under no viewer.
    viewer.id = null;
    const { result } = renderHook(() => useCoralScope(), { wrapper });
    expect(result.current).toEqual({ scope: coralScope(null, "/"), ready: false });
  });

  it("keeps one object while nothing it holds changes", () => {
    // WHY: callers memoize keys and effects on it.
    const { result, rerender } = renderHook(() => useCoralScope(), { wrapper });
    const first = result.current;
    rerender();
    expect(result.current).toBe(first);
  });
});

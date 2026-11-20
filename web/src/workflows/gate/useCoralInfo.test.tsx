import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import {
  CoralInfoError,
  fetchCoralInfo,
  isCoralAvailable,
  isCoralMissingError,
  shouldRetryCoralInfo,
  useCoralInfo,
} from "./useCoralInfo";

const INFO = { enabled: true, version: "1.2.3", sub_features: { profiles_desk: true } };

function wrapper() {
  const client = new QueryClient();
  return {
    client,
    Wrapper: ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    ),
  };
}

const respond = (status: number, body: unknown = INFO) =>
  new Response(JSON.stringify(body), { status });

beforeEach(() => {
  authenticatedFetch.mockReset();
});

describe("useCoralInfo", () => {
  it("fetches /v1/coral/info under the coral-info key", async () => {
    authenticatedFetch.mockResolvedValue(respond(200));
    const { client, Wrapper } = wrapper();
    const { result } = renderHook(() => useCoralInfo(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.data).toEqual(INFO));
    expect(authenticatedFetch).toHaveBeenCalledWith("/v1/coral/info", expect.anything());
    expect(client.getQueryData(["coral-info"])).toEqual(INFO);
  });

  it("does not retry a 404", async () => {
    authenticatedFetch.mockResolvedValue(respond(404, {}));
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useCoralInfo(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(authenticatedFetch).toHaveBeenCalledTimes(1);
    expect(isCoralMissingError(result.current.error)).toBe(true);
  });

  it("retries a 5xx once, then reports the error", async () => {
    authenticatedFetch.mockResolvedValue(respond(503, {}));
    const { Wrapper } = wrapper();
    const { result } = renderHook(() => useCoralInfo(), { wrapper: Wrapper });

    await waitFor(() => expect(result.current.isError).toBe(true), { timeout: 4000 });
    expect(authenticatedFetch).toHaveBeenCalledTimes(2);
    expect(isCoralMissingError(result.current.error)).toBe(false);
  });

  it("asks nothing while disabled, then fetches once enabled", async () => {
    // WHY: app-wide callers wait for the viewer's identity before probing Coral.
    authenticatedFetch.mockResolvedValue(respond(200));
    const { Wrapper } = wrapper();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) => useCoralInfo({ enabled }),
      { wrapper: Wrapper, initialProps: { enabled: false } },
    );
    expect(authenticatedFetch).not.toHaveBeenCalled();
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.data).toEqual(INFO));
  });
});

describe("fetchCoralInfo", () => {
  it("rejects a malformed payload", async () => {
    authenticatedFetch.mockResolvedValue(respond(200, { enabled: "yes" }));
    await expect(fetchCoralInfo()).rejects.toBeInstanceOf(CoralInfoError);
  });
});

describe("shouldRetryCoralInfo", () => {
  it("retries network and 5xx failures once, never 4xx", () => {
    expect(shouldRetryCoralInfo(0, new TypeError("offline"))).toBe(true);
    expect(shouldRetryCoralInfo(1, new TypeError("offline"))).toBe(false);
    expect(shouldRetryCoralInfo(0, new CoralInfoError("x", 500))).toBe(true);
    expect(shouldRetryCoralInfo(0, new CoralInfoError("x", 404))).toBe(false);
    expect(shouldRetryCoralInfo(0, new CoralInfoError("x", 403))).toBe(false);
  });
});

describe("isCoralAvailable", () => {
  it("requires enabled and, when named, the sub-feature", () => {
    expect(isCoralAvailable(undefined)).toBe(false);
    expect(isCoralAvailable({ ...INFO, enabled: false })).toBe(false);
    expect(isCoralAvailable(INFO)).toBe(true);
    expect(isCoralAvailable(INFO, "profiles_desk")).toBe(true);
    expect(isCoralAvailable(INFO, "missing")).toBe(false);
  });
});

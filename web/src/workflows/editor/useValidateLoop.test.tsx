import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MINIMAL_COMPILED, PR_REVIEW_COMPILED } from "../fixtures";

const validateWorkflow = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({ validateWorkflow }));

import { VALIDATE_DEBOUNCE_MS, useValidateLoop } from "./useValidateLoop";

beforeEach(() => {
  vi.useFakeTimers();
  validateWorkflow.mockReset();
});
afterEach(() => vi.useRealTimers());

async function flush() {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(VALIDATE_DEBOUNCE_MS);
  });
}

describe("useValidateLoop", () => {
  it("debounces edits into one validate call", async () => {
    validateWorkflow.mockResolvedValue({ valid: true, runnable: true, compiled: MINIMAL_COMPILED });
    const { result, rerender } = renderHook(({ yaml }) => useValidateLoop(yaml), {
      initialProps: { yaml: "a" },
    });
    rerender({ yaml: "ab" });
    rerender({ yaml: "abc" });
    expect(validateWorkflow).not.toHaveBeenCalled();
    expect(result.current.isValidating).toBe(true);

    await flush();
    expect(validateWorkflow).toHaveBeenCalledTimes(1);
    expect(validateWorkflow.mock.calls[0][0]).toBe("abc");
    expect(result.current.compiled).toBe(MINIMAL_COMPILED);
    expect(result.current.isValidating).toBe(false);
  });

  it("keeps the last compiled graph while the text fails to load", async () => {
    validateWorkflow.mockResolvedValueOnce({
      valid: true,
      runnable: true,
      compiled: PR_REVIEW_COMPILED,
    });
    const { result, rerender } = renderHook(({ yaml }) => useValidateLoop(yaml), {
      initialProps: { yaml: "ok" },
    });
    await flush();
    validateWorkflow.mockResolvedValueOnce({
      valid: false,
      runnable: false,
      load_error: { code: "invalid_yaml", yaml_path: "", range: null, message: "x", issues: [] },
    });
    rerender({ yaml: "id: [oops" });
    await flush();
    expect(result.current.response?.valid).toBe(false);
    expect(result.current.compiled).toBe(PR_REVIEW_COMPILED);
  });

  it("surfaces request failures", async () => {
    validateWorkflow.mockRejectedValue(new Error("offline"));
    const { result } = renderHook(() => useValidateLoop("x"));
    await flush();
    expect(result.current.error?.message).toBe("offline");
    expect(result.current.isValidating).toBe(false);
  });
});

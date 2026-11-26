import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { InvalidResult, SimResult, SimulatedResult } from "../api/generated/coralApi";
import type * as ClientModule from "../api/client";
import { WorkflowsApiError } from "../api/client";
import { MAX_RETRY_AFTER_MS } from "../api/runsApi";
import { REVIEW_LOOP_COMPILED, REVIEW_LOOP_SIMULATIONS } from "../fixtures";

const api = vi.hoisted(() => ({ simulateWorkflow: vi.fn() }));
vi.mock("../api/client", async (importOriginal) => ({
  ...(await importOriginal<typeof ClientModule>()),
  ...api,
}));

import { BUSY_RETRIES, useSimulation } from "./useSimulation";

const simulated = (simulation: SimResult | null): SimulatedResult => ({
  valid: true,
  runnable: simulation !== null,
  content_hash: REVIEW_LOOP_COMPILED.content_hash,
  problems: [],
  compiled: REVIEW_LOOP_COMPILED,
  simulation,
});

const NOT_LOADED: InvalidResult = {
  valid: false,
  runnable: false,
  load_error: { code: "invalid_yaml", yaml_path: "", range: null, message: "Bad.", issues: [] },
};

const busy = (retryAfterMs: number | null) =>
  new WorkflowsApiError("Failed to simulate workflow (503)", 503, retryAfterMs, "server_busy");

const REJECTED: SimResult = {
  ...REVIEW_LOOP_SIMULATIONS.needs_review,
  outcome: "rejected",
  needs_input: null,
  rejection: {
    node_id: "review",
    kind: "label",
    value: "approved",
    code: "handoff.invalid",
    allowed_values: ["changes_requested"],
  },
};
const CHANGES_REQUESTED = { node_id: "review", kind: "label", values: ["changes_requested"] };

/** An answer the test releases. */
function held<T>() {
  let release: (value: T) => void = () => {};
  const promise = new Promise<T>((resolve) => {
    release = resolve;
  });
  return { promise, release };
}

const signalOf = (call: number): AbortSignal => api.simulateWorkflow.mock.calls[call][2];

function renderSimulation(yaml = "v1", enabled = true) {
  return renderHook(({ yaml: text, enabled: open }) => useSimulation(text, open), {
    initialProps: { yaml, enabled },
  });
}

beforeEach(() => {
  api.simulateWorkflow.mockReset();
  api.simulateWorkflow.mockResolvedValue(simulated(REVIEW_LOOP_SIMULATIONS.needs_review));
});
afterEach(() => vi.useRealTimers());

describe("useSimulation", () => {
  it("posts the YAML with an empty script when it opens, and nothing while closed", async () => {
    const { result, rerender } = renderSimulation("v1", false);
    expect(api.simulateWorkflow).not.toHaveBeenCalled();
    expect(result.current.response).toBeNull();

    rerender({ yaml: "v1", enabled: true });
    expect(result.current.isPending).toBe(true);
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenCalledWith("v1", { inputs: [] }, expect.anything());
    expect(result.current.simulation).toEqual(REVIEW_LOOP_SIMULATIONS.needs_review);
    expect(result.current.compiled).toBe(REVIEW_LOOP_COMPILED);
    expect(result.current.overlay?.get("review")?.state).toBe("running");
    expect(result.current.stale).toBe(false);
  });

  it("posts a preset script while open, as answers that round-trip to the same script", async () => {
    const script = {
      inputs: [
        { node_id: "review", kind: "label" as const, values: ["changes_requested", "approved"] },
        { node_id: "approve_change", kind: "gate" as const, values: ["approve"] },
      ],
    };
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => result.current.runScript(script));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v1", script, expect.anything());
    expect(result.current.answers).toEqual([
      { nodeId: "review", kind: "label", value: "changes_requested" },
      { nodeId: "review", kind: "label", value: "approved" },
      { nodeId: "approve_change", kind: "gate", value: "approve" },
    ]);
  });

  it("posts a preset given while closed when it opens, instead of an empty script", async () => {
    const script = {
      inputs: [{ node_id: "review", kind: "label" as const, values: ["approved"] }],
    };
    const { result, rerender } = renderSimulation("v1", false);
    act(() => result.current.runScript(script));
    expect(api.simulateWorkflow).not.toHaveBeenCalled();
    rerender({ yaml: "v1", enabled: true });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    expect(api.simulateWorkflow).toHaveBeenCalledWith("v1", script, expect.anything());

    rerender({ yaml: "v1", enabled: false });
    rerender({ yaml: "v1", enabled: true });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v1", { inputs: [] }, expect.anything());
  });

  it("posts an empty script for a preset without inputs", async () => {
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    api.simulateWorkflow.mockClear();
    act(() => result.current.runScript({}));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenCalledWith("v1", { inputs: [] }, expect.anything());
  });

  it("never posts while the YAML changes; it reports the result stale", async () => {
    // WHY: answers belong to the text they were chosen for; only an explicit re-run moves on.
    const { result, rerender } = renderSimulation("v1");
    await waitFor(() => expect(result.current.isPending).toBe(false));
    rerender({ yaml: "v2", enabled: true });
    rerender({ yaml: "v3", enabled: true });
    expect(result.current.stale).toBe(true);
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);

    act(() => result.current.rerun());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v3", { inputs: [] }, expect.anything());
    expect(result.current.stale).toBe(false);
  });

  it("aborts an older request when a newer one starts, and ignores its answer", async () => {
    const first = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(first.promise);
    const { result, rerender } = renderSimulation("v1");
    rerender({ yaml: "v2", enabled: true });
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.approved));
    act(() => result.current.rerun());
    expect(signalOf(0).aborted).toBe(true);
    await waitFor(() => expect(result.current.isPending).toBe(false));

    await act(async () => first.release(simulated(REVIEW_LOOP_SIMULATIONS.needs_review)));
    expect(result.current.simulation?.outcome).toBe("completed");
  });

  it("appends an answer to the question asked, and undo and reset re-post without it", async () => {
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));

    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.needs_gate));
    act(() => result.current.answer("approved"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.answers).toEqual([
      { nodeId: "review", kind: "label", value: "approved" },
    ]);
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.approved));
    act(() => result.current.answer("approve"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
      "v1",
      {
        inputs: [
          { node_id: "review", kind: "label", values: ["approved"] },
          { node_id: "approve_change", kind: "gate", values: ["approve"] },
        ],
      },
      expect.anything(),
    );

    act(() => result.current.undo());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
      "v1",
      { inputs: [{ node_id: "review", kind: "label", values: ["approved"] }] },
      expect.anything(),
    );
    act(() => result.current.reset());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v1", { inputs: [] }, expect.anything());
    expect(result.current.answers).toEqual([]);
  });

  it("takes no answer while a request is in flight, while stale, or without a question", async () => {
    // WHY: an answer must belong to the question on screen and to the text it came from.
    const pending = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(pending.promise);
    const { result, rerender } = renderSimulation();
    act(() => result.current.answer("approved"));
    act(() => result.current.undo());
    act(() => result.current.reset());
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    await act(async () => pending.release(simulated(REVIEW_LOOP_SIMULATIONS.needs_review)));

    rerender({ yaml: "v2", enabled: true });
    act(() => result.current.answer("approved"));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);

    rerender({ yaml: "v1", enabled: true });
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.approved));
    act(() => result.current.answer("approved"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => result.current.answer("approve"));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);
  });

  it("ignores the failure of a request a newer one aborted", async () => {
    // WHY: fetch rejects an aborted request; that must not replace the newer request's answer.
    api.simulateWorkflow.mockImplementationOnce(
      (_yaml: string, _script: unknown, signal: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        }),
    );
    const { result, rerender } = renderSimulation("v1");
    rerender({ yaml: "v2", enabled: true });
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.approved));
    act(() => result.current.rerun());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.error).toBeNull();
    expect(result.current.simulation?.outcome).toBe("completed");
  });

  it("takes no answer after a rejection, has nothing to undo at empty, and undoes once per tick", async () => {
    // WHY: a refused value leaves no question to answer; a double click on Undo drops one answer.
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    api.simulateWorkflow.mockResolvedValueOnce(simulated(REJECTED));
    act(() => result.current.answer("approved"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => result.current.answer("changes_requested"));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);

    act(() => result.current.undo());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v1", { inputs: [] }, expect.anything());
    act(() => result.current.undo());
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(3);

    act(() => result.current.answer("changes_requested"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => result.current.answer("changes_requested"));
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => {
      result.current.undo();
      result.current.undo();
      result.current.reset();
    });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(6);
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith(
      "v1",
      { inputs: [CHANGES_REQUESTED] },
      expect.anything(),
    );
  });

  it("closing aborts the request and forgets the answers; opening starts over", async () => {
    const { result, rerender } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    act(() => result.current.answer("approved"));
    rerender({ yaml: "v1", enabled: false });
    expect(signalOf(1).aborted).toBe(true);
    expect(result.current).toMatchObject({ response: null, answers: [], isPending: false });

    rerender({ yaml: "v1", enabled: true });
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(api.simulateWorkflow).toHaveBeenLastCalledWith("v1", { inputs: [] }, expect.anything());
  });

  it("derives no graph or overlay from a text that does not load or cannot run", async () => {
    api.simulateWorkflow.mockResolvedValueOnce(NOT_LOADED);
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current).toMatchObject({ response: NOT_LOADED, compiled: null, overlay: null });

    api.simulateWorkflow.mockResolvedValueOnce(simulated(null));
    act(() => result.current.rerun());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.compiled).toBe(REVIEW_LOOP_COMPILED);
    expect(result.current.simulation).toBeNull();
    expect(result.current.overlay).toBeNull();
  });

  it("waits out a busy server's Retry-After, then posts the same request again", async () => {
    // WHY: the server allows one simulation per person; an aborted one may still hold it.
    vi.useFakeTimers();
    api.simulateWorkflow
      .mockRejectedValueOnce(busy(2000))
      .mockResolvedValueOnce(simulated(REVIEW_LOOP_SIMULATIONS.needs_review));
    const { result } = renderSimulation();
    await act(async () => {});
    expect(result.current).toMatchObject({ busy: true, isPending: true, error: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1999);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);
    expect(api.simulateWorkflow.mock.calls[1].slice(0, 2)).toEqual(["v1", { inputs: [] }]);
    expect(result.current).toMatchObject({ busy: false, isPending: false });
    expect(result.current.simulation?.outcome).toBe("needs_input");
  });

  it("waits at least a second and at most a minute, and gives up after a few tries", async () => {
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValue(busy(null));
    const { result } = renderSimulation();
    await act(async () => {});
    await act(async () => {
      await vi.advanceTimersByTimeAsync(999);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);

    api.simulateWorkflow.mockRejectedValue(busy(3_600_000));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(MAX_RETRY_AFTER_MS * BUSY_RETRIES);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(BUSY_RETRIES + 1);
    expect(result.current).toMatchObject({ busy: false, isPending: false });
    expect(result.current.error).toMatchObject({ status: 503 });
  });

  it("waits a second when Retry-After asks for none, and exactly the longest wait at most", async () => {
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValueOnce(busy(0)).mockRejectedValueOnce(busy(3_600_000));
    renderSimulation();
    await act(async () => {});
    const advance = (ms: number) =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(ms);
      });
    await advance(999);
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);
    await advance(MAX_RETRY_AFTER_MS - 1);
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(2);
    await advance(1);
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(3);
  });

  it("posts the same answers and text after a busy refusal, though the YAML changed meanwhile", async () => {
    // WHY: the retry is the request the person made; an edit waits for "Simulate again".
    const { result, rerender } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValueOnce(busy(1000));
    act(() => result.current.answer("changes_requested"));
    await act(async () => {});
    rerender({ yaml: "v2", enabled: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(api.simulateWorkflow.mock.calls.map((call) => call.slice(0, 2))).toEqual([
      ["v1", { inputs: [] }],
      ["v1", { inputs: [CHANGES_REQUESTED] }],
      ["v1", { inputs: [CHANGES_REQUESTED] }],
    ]);
    expect(result.current).toMatchObject({ stale: true, busy: false, isPending: false });
  });

  it("stops waiting for a busy server once a newer request starts or the panel closes", async () => {
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValueOnce(busy(5000));
    const { result, rerender } = renderSimulation();
    await act(async () => {});
    expect(result.current.busy).toBe(true);
    rerender({ yaml: "v2", enabled: true });
    act(() => result.current.rerun());
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(api.simulateWorkflow.mock.calls.map((call) => call[0])).toEqual(["v1", "v2"]);

    api.simulateWorkflow.mockRejectedValueOnce(busy(5000));
    act(() => result.current.rerun());
    await act(async () => {});
    rerender({ yaml: "v2", enabled: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(3);
  });

  it("drops the previous text's result while the edited text is simulated, and stays stale", async () => {
    // WHY: a result shows only for the YAML it was simulated from.
    const { result, rerender } = renderSimulation("v1");
    await waitFor(() => expect(result.current.isPending).toBe(false));
    rerender({ yaml: "v2", enabled: true });

    const edited = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(edited.promise);
    act(() => result.current.rerun());
    expect(result.current).toMatchObject({
      response: null,
      simulation: null,
      compiled: null,
      overlay: null,
      stale: true,
      isPending: true,
      canRerun: false,
    });

    await act(async () => edited.release(simulated(REVIEW_LOOP_SIMULATIONS.needs_review)));
    expect(result.current).toMatchObject({ stale: false, isPending: false, canRerun: true });
    expect(result.current.overlay).not.toBeNull();
  });

  it("keeps the result on screen while the same text is simulated with another answer", async () => {
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    const answered = held<SimulatedResult>();
    api.simulateWorkflow.mockReturnValueOnce(answered.promise);
    act(() => result.current.answer("approved"));
    expect(result.current.isPending).toBe(true);
    expect(result.current.simulation).toEqual(REVIEW_LOOP_SIMULATIONS.needs_review);
    expect(result.current.stale).toBe(false);
  });

  it("is no longer stale once a request for the edited text fails", async () => {
    const { result, rerender } = renderSimulation("v1");
    await waitFor(() => expect(result.current.isPending).toBe(false));
    rerender({ yaml: "v2", enabled: true });
    api.simulateWorkflow.mockRejectedValueOnce(new WorkflowsApiError("Failed (500)", 500));
    act(() => result.current.rerun());
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current).toMatchObject({ response: null, stale: false });
    expect(result.current.error).toMatchObject({ status: 500 });
  });

  it("posts again only after the server's own busy refusal, not after any 503", async () => {
    // WHY: a proxy's 503 is a failure to report, not a queue to wait in.
    vi.useFakeTimers();
    api.simulateWorkflow.mockRejectedValueOnce(
      new WorkflowsApiError("Failed to simulate workflow (503)", 503, 1000, null),
    );
    const { result } = renderSimulation();
    await act(async () => {});
    expect(result.current).toMatchObject({ busy: false, isPending: false });
    expect(result.current.error).toMatchObject({ status: 503, code: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(api.simulateWorkflow).toHaveBeenCalledTimes(1);
  });

  it("reports another failure as an error without a response", async () => {
    api.simulateWorkflow.mockRejectedValueOnce(new WorkflowsApiError("Failed (500)", 500));
    const { result } = renderSimulation();
    await waitFor(() => expect(result.current.isPending).toBe(false));
    expect(result.current.error).toMatchObject({ status: 500 });
    expect(result.current.response).toBeNull();
  });
});

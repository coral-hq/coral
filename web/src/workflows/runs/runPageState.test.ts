import { describe, expect, it } from "vitest";
import { ApiError } from "@/lib/sessionsApi";
import { CoralRequestError } from "../api/runsApi";
import type { RunStreamStatus } from "../stream/runStream";
import { connectionNotice, runPageState, type RunPageInputs } from "./runPageState";

const LOADED: RunPageInputs = {
  detailError: null,
  detailLoaded: true,
  streamShown: true,
  streamStatus: "live",
  streamRetrying: false,
};

const state = (changes: Partial<RunPageInputs>) => runPageState({ ...LOADED, ...changes });

describe("runPageState", () => {
  it("waits for the detail or the stream before showing the run", () => {
    // WHY: with neither, there is nothing true to show.
    expect(state({ detailLoaded: false, streamShown: false, streamStatus: "connecting" })).toBe(
      "loading",
    );
    expect(state({ detailLoaded: false })).toBe("ready");
    expect(state({ streamShown: false, streamStatus: "connecting" })).toBe("ready");
  });

  it("ends at not found when either source answers 404", () => {
    // WHY: both check the owner, and another user's run reads as missing.
    const notFound = new CoralRequestError("Run not found.", 404, "not_found", null);
    expect(state({ detailError: notFound })).toBe("not_found");
    expect(state({ detailError: new ApiError("Not Found", 404, null) })).toBe("not_found");
    expect(state({ streamStatus: "not_found" })).toBe("not_found");
  });

  it("fails with Retry on a refused stream or a detail that never loaded", () => {
    // WHY: those leave nothing the page can stand on until the owner tries again.
    expect(state({ streamStatus: "failed" })).toBe("failed");
    expect(state({ detailError: new ApiError("boom", 500, null), detailLoaded: false })).toBe(
      "failed",
    );
  });

  it("stays failed after Retry until the restarted stream sends a frame", () => {
    // WHY: the cached view is not news; showing it as live would offer stale actions.
    expect(state({ streamStatus: "live", streamRetrying: true })).toBe("failed");
    expect(state({ streamStatus: "not_found", streamRetrying: true })).toBe("not_found");
  });

  it("keeps showing a loaded detail when a later read fails", () => {
    // WHY: a passing server error must not blank a page that has the run.
    expect(state({ detailError: new ApiError("boom", 500, null) })).toBe("ready");
  });
});

describe("connectionNotice", () => {
  it.each<[RunStreamStatus, string | null]>([
    ["reconnecting", "Reconnecting…"],
    ["limited", "Live updates limited"],
    ["outdated", "This page is out of date. Reload it for live updates."],
    ["connecting", null],
    ["live", null],
    ["paused_hidden", null],
    ["done", null],
    ["not_found", null],
    ["failed", null],
  ])("says %s as %j", (status, text) => {
    // WHY: the page says when live updates stop, and nothing while they flow or it is hidden.
    expect(connectionNotice(status)).toBe(text);
  });
});

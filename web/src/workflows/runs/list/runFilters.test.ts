import { describe, expect, it } from "vitest";
import {
  ALL_RUNS,
  RUN_STATUS_CHIPS,
  runListFilters,
  runsQueryFilters,
  searchWithRunFilters,
  type RunListFilters,
} from "./runFilters";

const WORKFLOW_ID = "0123456789abcdef0123456789abcdef";

const search = (query: string) => new URLSearchParams(query);

describe("runListFilters", () => {
  it("reads the status chip and workflow the URL names", () => {
    // WHY: a shared or reloaded link opens the same filtered list.
    expect(runListFilters(search(`tab=runs&status=paused&workflow=${WORKFLOW_ID}`))).toEqual({
      status: "paused",
      workflowId: WORKFLOW_ID,
    });
  });

  it("reads no filters as every run", () => {
    expect(runListFilters(search("tab=runs"))).toEqual(ALL_RUNS);
  });

  it.each([
    ["an unknown status", "status=bogus", ALL_RUNS],
    ["a raw run status the chips do not name", "status=starting", ALL_RUNS],
    ["an inherited key", "status=constructor", ALL_RUNS],
    ["a workflow id that is not 32 hex", "workflow=W1", ALL_RUNS],
    ["an upper-case workflow id", `workflow=${WORKFLOW_ID.toUpperCase()}`, ALL_RUNS],
    ["an empty workflow", "workflow=", ALL_RUNS],
  ])("ignores %s, which the server would refuse", (_name, query, expected) => {
    // WHY: a hand-edited URL lists runs instead of failing with a 422.
    expect(runListFilters(search(query))).toEqual(expected);
  });
});

describe("repeated filter parameters", () => {
  it("reads the first of a repeated parameter, and writes back one", () => {
    // WHY: a pasted or hand-joined link can repeat a key; the list and the URL must agree.
    const repeated = search(`status=paused&status=failed&workflow=nope&workflow=${WORKFLOW_ID}`);
    expect(runListFilters(repeated)).toEqual({ status: "paused", workflowId: null });
    const next = searchWithRunFilters(repeated, { status: "failed", workflowId: WORKFLOW_ID });
    expect(next.getAll("status")).toEqual(["failed"]);
    expect(next.getAll("workflow")).toEqual([WORKFLOW_ID]);
  });
});

describe("runsQueryFilters", () => {
  it("asks for starting and running runs under Running", () => {
    // WHY: a run still setting up is running as far as the person is concerned.
    expect(runsQueryFilters({ status: "running", workflowId: null })).toEqual({
      statuses: ["starting", "running"],
      workflowId: null,
    });
  });

  it("asks for every status under All, and one status under each other chip", () => {
    expect(runsQueryFilters({ status: "all", workflowId: WORKFLOW_ID })).toEqual({
      statuses: [],
      workflowId: WORKFLOW_ID,
    });
    for (const status of ["paused", "completed", "failed", "cancelled"] as const) {
      expect(runsQueryFilters({ status, workflowId: null }).statuses).toEqual([status]);
    }
  });

  it("offers the chips in order, All first", () => {
    expect(RUN_STATUS_CHIPS.map((chip) => chip.label)).toEqual([
      "All",
      "Running",
      "Paused",
      "Completed",
      "Failed",
      "Cancelled",
    ]);
  });
});

describe("searchWithRunFilters", () => {
  it("writes the filters beside the URL's other parameters", () => {
    const next = searchWithRunFilters(search("tab=runs"), {
      status: "failed",
      workflowId: WORKFLOW_ID,
    });
    expect(next.toString()).toBe(`tab=runs&status=failed&workflow=${WORKFLOW_ID}`);
  });

  it("drops a filter set back to its default", () => {
    // WHY: the plain list keeps a plain URL.
    const next = searchWithRunFilters(search(`tab=runs&status=paused&workflow=${WORKFLOW_ID}`), {
      status: "all",
      workflowId: null,
    });
    expect(next.toString()).toBe("tab=runs");
  });

  it("round-trips through runListFilters without touching its input", () => {
    const input = search("tab=runs");
    const filters: RunListFilters = { status: "cancelled", workflowId: WORKFLOW_ID };
    expect(runListFilters(searchWithRunFilters(input, filters))).toEqual(filters);
    expect(input.toString()).toBe("tab=runs");
  });
});

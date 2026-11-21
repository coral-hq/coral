import { beforeEach, describe, expect, it, vi } from "vitest";
import { MINIMAL_COMPILED } from "../fixtures";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import {
  WorkflowsApiError,
  getWorkflowByKey,
  listTemplates,
  listWorkflows,
  validateWorkflow,
} from "./client";

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

beforeEach(() => authenticatedFetch.mockReset());

describe("workflows client", () => {
  it("posts YAML to the validate endpoint and returns compiled", async () => {
    authenticatedFetch.mockResolvedValue(
      json({ valid: true, runnable: true, compiled: MINIMAL_COMPILED }),
    );
    const result = await validateWorkflow("id: demo");
    expect(result.compiled).toEqual(MINIMAL_COMPILED);
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/workflows:validate");
    expect(JSON.parse(init.body)).toEqual({ yaml: "id: demo" });
  });

  it("resolves a workflow key through the list, then fetches the definition", async () => {
    authenticatedFetch
      .mockResolvedValueOnce(json([{ id: "id-1", workflow_key: "demo" }]))
      .mockResolvedValueOnce(json({ id: "id-1", workflow_key: "demo", yaml: "y" }));
    expect((await getWorkflowByKey("demo")).yaml).toBe("y");
    expect(authenticatedFetch.mock.calls[1][0]).toBe("/v1/coral/workflows/id-1");
  });

  it("raises a 404 for an unknown key and rejects non-list payloads", async () => {
    authenticatedFetch.mockResolvedValueOnce(json([]));
    await expect(getWorkflowByKey("ghost")).rejects.toMatchObject({ status: 404 });
    authenticatedFetch.mockResolvedValueOnce(json({ enabled: true }));
    await expect(listWorkflows()).rejects.toBeInstanceOf(WorkflowsApiError);
  });

  it("raises on HTTP failures", async () => {
    authenticatedFetch.mockResolvedValue(json({}, 500));
    await expect(validateWorkflow("x")).rejects.toMatchObject({ status: 500 });
  });

  it("serves templates locally until their API exists", async () => {
    expect((await listTemplates())[0].id).toBe("pr-review");
    expect(authenticatedFetch).not.toHaveBeenCalled();
  });
});

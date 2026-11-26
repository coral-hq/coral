import { beforeEach, describe, expect, it, vi } from "vitest";
import { MINIMAL_COMPILED } from "../fixtures";

const authenticatedFetch = vi.hoisted(() => vi.fn());
vi.mock("@/lib/identity", () => ({ authenticatedFetch }));

import {
  WorkflowsApiError,
  createFromTemplate,
  deleteWorkflowCase,
  getWorkflowByKey,
  listTemplates,
  listWorkflowCases,
  listWorkflows,
  saveWorkflowCase,
  simulateWorkflow,
  validateWorkflow,
  workflowCasesQueryKey,
} from "./client";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), { status, headers });

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

  it("lists the server's templates and rejects a payload that is not a list", async () => {
    const template = { id: "implement-review-loop", name: "N", description: "D", yaml: "y" };
    authenticatedFetch.mockResolvedValueOnce(json([template]));
    expect(await listTemplates()).toEqual([template]);
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/templates");
    expect(init.method).toBeUndefined();

    authenticatedFetch.mockResolvedValueOnce(json({ templates: [] }));
    await expect(listTemplates()).rejects.toBeInstanceOf(WorkflowsApiError);
  });

  it("makes a copy of a template by posting an empty JSON object to its use route", async () => {
    // WHY: the route takes an empty JSON body, and a cross-site form post is refused.
    authenticatedFetch.mockResolvedValue(json({ workflow_key: "implement-review-loop-2" }, 201));
    expect((await createFromTemplate("implement-review-loop")).workflow_key).toBe(
      "implement-review-loop-2",
    );
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/templates/implement-review-loop:use");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    expect(JSON.parse(init.body)).toEqual({});
  });

  it("encodes the template id into one path segment", async () => {
    authenticatedFetch.mockResolvedValue(json({ workflow_key: "k" }, 201));
    await createFromTemplate("a/b?c#d");
    expect(authenticatedFetch.mock.calls[0][0]).toBe("/v1/coral/templates/a%2Fb%3Fc%23d:use");
  });

  it("posts the YAML and the script to the simulate endpoint", async () => {
    const response = { valid: false, runnable: false, load_error: { message: "x" } };
    authenticatedFetch.mockResolvedValue(json(response));
    const controller = new AbortController();
    const script = {
      inputs: [{ node_id: "review", kind: "label" as const, values: ["approved"] }],
    };
    expect(await simulateWorkflow("id: demo", script, controller.signal)).toEqual(response);
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/workflows:simulate");
    expect(init.method).toBe("POST");
    expect(init.signal).toBe(controller.signal);
    expect(JSON.parse(init.body)).toEqual({ yaml: "id: demo", script });
  });

  it("keeps a refusal's status, Retry-After and code", async () => {
    // WHY: only a 503 whose code is server_busy is waited out and posted again.
    const envelope = { error: { code: "server_busy", message: "Busy.", details: null } };
    authenticatedFetch.mockResolvedValueOnce(json(envelope, 503, { "Retry-After": "2" }));
    await expect(simulateWorkflow("x", { inputs: [] })).rejects.toMatchObject({
      name: "WorkflowsApiError",
      status: 503,
      retryAfterMs: 2000,
      code: "server_busy",
    });
    authenticatedFetch.mockResolvedValueOnce(json({}, 404));
    await expect(createFromTemplate("nope")).rejects.toMatchObject({
      status: 404,
      retryAfterMs: null,
      code: null,
    });
    authenticatedFetch.mockResolvedValueOnce(new Response("Service Unavailable", { status: 503 }));
    await expect(simulateWorkflow("x", { inputs: [] })).rejects.toMatchObject({
      status: 503,
      code: null,
    });
  });

  it("lists a workflow's cases and rejects a payload that is not a list", async () => {
    const saved = { id: "c1", name: "N" };
    authenticatedFetch.mockResolvedValueOnce(json([saved]));
    const controller = new AbortController();
    expect(await listWorkflowCases("w/1", controller.signal)).toEqual([saved]);
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/workflows/w%2F1/cases");
    expect(init).toEqual({ signal: controller.signal });

    authenticatedFetch.mockResolvedValueOnce(json({ cases: [] }));
    await expect(listWorkflowCases("w1")).rejects.toBeInstanceOf(WorkflowsApiError);
    expect(workflowCasesQueryKey("w1")).toEqual(["coral-workflow-cases", "w1"]);
  });

  it("posts a case to the workflow's cases and keeps a refusal's code", async () => {
    const body = {
      name: "Approved",
      script: { inputs: [{ node_id: "review", kind: "label" as const, values: ["approved"] }] },
      expect: { outcome: "completed" as const, steps: ["review:approved"] },
    };
    authenticatedFetch.mockResolvedValueOnce(json({ id: "c1", ...body }, 201));
    expect((await saveWorkflowCase("w?1", body)).id).toBe("c1");
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/workflows/w%3F1/cases");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body)).toEqual(body);

    const envelope = { error: { code: "case_exists", message: "Taken.", details: null } };
    authenticatedFetch.mockResolvedValueOnce(json(envelope, 409));
    await expect(saveWorkflowCase("w1", body)).rejects.toMatchObject({
      status: 409,
      code: "case_exists",
    });
  });

  it("deletes a case, reading no body from the 204", async () => {
    authenticatedFetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(deleteWorkflowCase("w1", "c/1#")).resolves.toBeUndefined();
    const [url, init] = authenticatedFetch.mock.calls[0];
    expect(url).toBe("/v1/coral/workflows/w1/cases/c%2F1%23");
    expect(init.method).toBe("DELETE");

    authenticatedFetch.mockResolvedValueOnce(json({}, 404));
    await expect(deleteWorkflowCase("w1", "c1")).rejects.toMatchObject({ status: 404 });
  });
});

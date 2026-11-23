import type {
  CapabilitiesOut,
  ProfileDetailOut,
  ProfileRowOut,
  ProfileSpec,
  RevisionIn,
  RuleTemplateOut,
} from "../api/generated/coralApi";

// Test-side stand-in for the profiles routes, in the shape of an MSW handler: a fake
// `authenticatedFetch` over an in-memory profile store that logs every request it gets.

export const CLAUDE_SDK_CAPABILITIES: CapabilitiesOut = {
  tool_gating: "supported",
  fs_read_only: "supported",
  steering: "unknown",
  usage_reporting: "unknown",
};

export const RULE_TEMPLATES: RuleTemplateOut[] = [
  {
    id: "protect_paths",
    version: 1,
    title: "Protect paths",
    params_schema: { properties: { paths: { type: "array", items: { type: "string" } } } },
    statement_example: "Never change files under infra/.",
    bypasses: ["Shell commands such as sed or a script can still write the files."],
  },
  {
    id: "limit_blast_radius",
    version: 1,
    title: "Limit blast radius",
    params_schema: { properties: {} },
    statement_example: "Never push, force-push or delete branches.",
    bypasses: ["Indirect shell, such as a script or alias that runs the command."],
  },
];

const seeded = (stance: string, name: string): ProfileRowOut => ({
  profile_ref: stance,
  stance,
  name,
  description: `The built-in ${stance}.`,
  harness: "claude-sdk",
  model: null,
  revision_no: null,
  source: "seeded",
  rules: [],
  capabilities: CLAUDE_SDK_CAPABILITIES,
  used_by: { workflows: 2, running_runs: 0 },
});

export const STRICT_REVIEW_SPEC: ProfileSpec = {
  name: "Strict review",
  description: "Reviews without touching infra.",
  instructions: "Review every change line by line.",
  model: "claude-sonnet-4-5",
  rules: [{ template: "protect_paths", strength: "required", params: { paths: ["infra"] } }],
};

export interface LoggedRequest {
  method: string;
  url: string;
  body: unknown;
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const envelope = (status: number, code: string, message: string, details: unknown = null) =>
  json({ error: { code, message, details } }, status);

/** A profiles server holding `reviewer/strict-review` at rev 1, used by 1 workflow and 1 run. */
export function profilesServer() {
  const requests: LoggedRequest[] = [];
  const specs: ProfileSpec[] = [STRICT_REVIEW_SPEC];

  const row = (): ProfileRowOut => {
    const spec = specs.at(-1)!;
    return {
      profile_ref: "reviewer/strict-review",
      stance: "reviewer",
      name: spec.name,
      description: spec.description,
      harness: "claude-sdk",
      model: spec.model,
      revision_no: specs.length,
      source: "user",
      rules: spec.rules.map((rule) => ({
        template: rule.template,
        strength: rule.strength,
        statement: "Never change files under infra/.",
      })),
      capabilities: CLAUDE_SDK_CAPABILITIES,
      // The run started on rev 1 keeps it; nothing is pinned to a later revision yet.
      used_by: { workflows: 1, running_runs: 1 },
    };
  };

  const detail = (created: boolean): ProfileDetailOut => ({
    ...row(),
    spec: specs.at(-1)!,
    created,
    revisions: specs
      .map((_, index) => ({
        id: `rev-${index + 1}`,
        revision_no: index + 1,
        created_at: 1_767_268_000 + index,
        running_runs: index === 0 ? 1 : 0,
      }))
      .reverse(),
  });

  async function handle(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
    const url = typeof input === "string" ? input : input.toString();
    const method = (init.method ?? "GET").toUpperCase();
    const body = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : null;
    requests.push({ method, url, body });
    const route = `${method} ${url}`;
    if (route === "GET /v1/coral/profiles") {
      return json([seeded("implementer", "Implementer"), seeded("reviewer", "Reviewer"), row()]);
    }
    if (route === "GET /v1/coral/rule-templates") return json(RULE_TEMPLATES);
    if (route === "GET /v1/coral/profiles/reviewer/strict-review") return json(detail(false));
    if (route === "POST /v1/coral/profiles/reviewer/strict-review/revisions") {
      const edit = body as RevisionIn;
      if (edit.base_revision_no !== specs.length) {
        return envelope(412, "stale_revision", "This profile has a newer revision.");
      }
      const spec = edit.spec as unknown as ProfileSpec;
      const same = JSON.stringify(spec) === JSON.stringify(specs.at(-1));
      if (!same) specs.push(spec);
      return json(detail(!same));
    }
    return envelope(405, "method_not_allowed", `No route for ${route}`);
  }

  return { handle, requests, specs };
}

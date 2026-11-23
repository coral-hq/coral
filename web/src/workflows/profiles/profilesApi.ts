import { authenticatedFetch } from "@/lib/identity";
import { coralError } from "../api/runsApi";
import type { CoralOperations, ProfileSpec } from "../api/generated/coralApi";

// The profiles client (`/v1/coral/profiles`, `/v1/coral/rule-templates`). An edit is a new
// revision posted against the revision it started from; profiles are never patched.

type Operation<Name extends keyof CoralOperations> = CoralOperations[Name];

const PROFILES_PATH = "/v1/coral/profiles" satisfies Operation<"coral_list_profiles">["path"];
const PROFILE_PATH =
  "/v1/coral/profiles/{stance}/{slug}" satisfies Operation<"coral_get_profile">["path"];
const REVISIONS_PATH =
  "/v1/coral/profiles/{stance}/{slug}/revisions" satisfies Operation<"coral_save_profile_revision">["path"];
const RULE_TEMPLATES_PATH =
  "/v1/coral/rule-templates" satisfies Operation<"coral_list_rule_templates">["path"];

export const PROFILES_QUERY_KEY = ["coral-profiles"] as const;
export const profileQueryKey = (ref: string) => ["coral-profile", ref] as const;
export const RULE_TEMPLATES_QUERY_KEY = ["coral-rule-templates"] as const;

/** Prefix of the built-in Coral agents, which are never a pickable profile. */
const RESERVED_PREFIX = "coral__";

export const isPickableProfile = (ref: string): boolean => !ref.startsWith(RESERVED_PREFIX);

function profileUrl(path: string, ref: string): string {
  const [stance = "", slug = ""] = ref.split("/");
  return path
    .replace("{stance}", () => encodeURIComponent(stance))
    .replace("{slug}", () => encodeURIComponent(slug));
}

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await coralError(response);
  return (await response.json()) as T;
}

function postJson(url: string, body: unknown): Promise<Response> {
  return authenticatedFetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** The built-in stances, then the caller's profiles. */
export async function listProfiles(
  signal?: AbortSignal,
): Promise<Operation<"coral_list_profiles">["response"]> {
  return readJson(await authenticatedFetch(PROFILES_PATH, { signal }));
}

/** One of the caller's profiles (`<stance>/<slug>`) with its spec and revisions. */
export async function getProfile(
  ref: string,
  signal?: AbortSignal,
): Promise<Operation<"coral_get_profile">["response"]> {
  return readJson(await authenticatedFetch(profileUrl(PROFILE_PATH, ref), { signal }));
}

export async function createProfile(
  ref: string,
  spec: ProfileSpec,
): Promise<Operation<"coral_create_profile">["response"]> {
  const body: Operation<"coral_create_profile">["body"] = { ref, spec: { ...spec } };
  return readJson(await postJson(PROFILES_PATH, body));
}

/** Save an edit made from `baseRevisionNo`; a newer revision on the server is a 412. */
export async function saveRevision(
  ref: string,
  baseRevisionNo: number,
  spec: ProfileSpec,
): Promise<Operation<"coral_save_profile_revision">["response"]> {
  const body: Operation<"coral_save_profile_revision">["body"] = {
    base_revision_no: baseRevisionNo,
    spec: { ...spec },
  };
  return readJson(await postJson(profileUrl(REVISIONS_PATH, ref), body));
}

export async function listRuleTemplates(
  signal?: AbortSignal,
): Promise<Operation<"coral_list_rule_templates">["response"]> {
  return readJson(await authenticatedFetch(RULE_TEMPLATES_PATH, { signal }));
}

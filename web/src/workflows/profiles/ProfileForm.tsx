import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError } from "@/lib/sessionsApi";
import type {
  ProfileSpec,
  RuleInstance,
  RuleStrength,
  RuleTemplateOut,
} from "../api/generated/coralApi";
import { CoralRequestError } from "../api/runsApi";
import { RULE_TEMPLATES_QUERY_KEY, listRuleTemplates } from "./profilesApi";

export const EMPTY_SPEC: ProfileSpec = {
  name: "",
  description: "",
  instructions: "",
  model: null,
  rules: [],
};

const STRENGTHS: readonly { value: RuleStrength; label: string }[] = [
  { value: "required", label: "Required" },
  { value: "guidance", label: "Guidance" },
];

const takesPaths = (template: RuleTemplateOut | undefined): boolean =>
  Object.hasOwn((template?.params_schema.properties as object | undefined) ?? {}, "paths");

const pathsOf = (rule: RuleInstance): string[] =>
  Array.isArray(rule.params.paths) ? (rule.params.paths as string[]) : [];

/** The spec as the API takes it: no blank paths, and a blank model is the harness default. */
export function cleanSpec(spec: ProfileSpec): ProfileSpec {
  return {
    ...spec,
    model: spec.model?.trim() ? spec.model.trim() : null,
    rules: spec.rules.map((rule) =>
      "paths" in rule.params
        ? {
            ...rule,
            params: {
              ...rule.params,
              paths: pathsOf(rule)
                .map((p) => p.trim())
                .filter(Boolean),
            },
          }
        : rule,
    ),
  };
}

/** A failed save as lines: the message, then each field a 422 names. */
export function errorLines(error: Error): string[] {
  const lines = [error.message];
  const errors = error instanceof CoralRequestError ? error.details?.errors : undefined;
  if (Array.isArray(errors)) {
    for (const item of errors as Record<string, unknown>[]) {
      // The route names `field`; FastAPI's body check names `loc`.
      const field = item.field ?? (Array.isArray(item.loc) ? item.loc.join(".") : null);
      const message = item.message ?? item.msg;
      if (typeof message === "string") lines.push(field ? `${String(field)}: ${message}` : message);
    }
  }
  // Unique, so each line can key itself.
  return [...new Set(lines)];
}

export const isStale = (error: unknown): boolean =>
  error instanceof ApiError && error.status === 412;

const fieldClass = "flex flex-col gap-1 text-ui";

export function ProfileForm({
  value,
  onChange,
  readOnly = false,
}: {
  value: ProfileSpec;
  onChange: (next: ProfileSpec) => void;
  readOnly?: boolean;
}) {
  const templates = useQuery({
    queryKey: RULE_TEMPLATES_QUERY_KEY,
    queryFn: ({ signal }) => listRuleTemplates(signal),
    staleTime: Infinity,
  });
  const byId = new Map((templates.data ?? []).map((t) => [t.id, t]));
  const set = (patch: Partial<ProfileSpec>) => onChange({ ...value, ...patch });
  const setRule = (index: number, rule: RuleInstance) =>
    set({ rules: value.rules.map((r, i) => (i === index ? rule : r)) });
  const unused = (templates.data ?? []).filter(
    (t) => !value.rules.some((rule) => rule.template === t.id),
  );
  const freshRule = (template: RuleTemplateOut, strength: RuleStrength): RuleInstance => ({
    template: template.id,
    strength,
    params: takesPaths(template) ? { paths: [""] } : {},
  });

  return (
    // A disabled fieldset disables every control in it.
    <fieldset disabled={readOnly} className="flex min-w-0 flex-col gap-4">
      <label className={fieldClass}>
        Name
        <Input value={value.name} maxLength={80} onChange={(e) => set({ name: e.target.value })} />
      </label>
      <label className={fieldClass}>
        Description
        <Input
          value={value.description}
          maxLength={500}
          onChange={(e) => set({ description: e.target.value })}
        />
      </label>
      <label className={fieldClass}>
        Instructions
        <Textarea
          value={value.instructions}
          maxLength={8000}
          rows={6}
          onChange={(e) => set({ instructions: e.target.value })}
        />
      </label>
      <label className={fieldClass}>
        Model
        <Input
          value={value.model ?? ""}
          placeholder="Harness default"
          onChange={(e) => set({ model: e.target.value })}
        />
      </label>
      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1 font-medium text-foreground text-ui">Rules</legend>
        {value.rules.map((rule, index) => {
          const template = byId.get(rule.template);
          const others = (templates.data ?? []).filter(
            (t) => t.id === rule.template || !value.rules.some((r) => r.template === t.id),
          );
          return (
            <div
              key={rule.template}
              className="flex flex-col gap-2 rounded-md border border-border p-3"
              data-testid="rule-editor"
            >
              <div className="flex flex-wrap items-center gap-2">
                <select
                  aria-label="Rule template"
                  value={rule.template}
                  onChange={(e) => {
                    const next = byId.get(e.target.value);
                    if (next) setRule(index, freshRule(next, rule.strength));
                  }}
                  className="h-7 rounded-md border border-border bg-background px-2 text-ui"
                >
                  {template === undefined && <option value={rule.template}>{rule.template}</option>}
                  {others.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
                {STRENGTHS.map((strength) => (
                  <label key={strength.value} className="flex items-center gap-1 text-ui">
                    <input
                      type="radio"
                      name={`strength-${rule.template}`}
                      checked={rule.strength === strength.value}
                      onChange={() => setRule(index, { ...rule, strength: strength.value })}
                    />
                    {strength.label}
                  </label>
                ))}
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  onClick={() => set({ rules: value.rules.filter((_, i) => i !== index) })}
                >
                  Remove
                </Button>
              </div>
              {takesPaths(template) && (
                <label className={fieldClass}>
                  Paths (one per line)
                  <Textarea
                    value={pathsOf(rule).join("\n")}
                    rows={2}
                    onChange={(e) =>
                      setRule(index, { ...rule, params: { paths: e.target.value.split("\n") } })
                    }
                  />
                </label>
              )}
              {template && (
                <p className="text-muted-foreground text-xs">
                  {`Example: ${template.statement_example}`}
                  {rule.strength === "guidance" &&
                    " Guidance is written into the instructions only."}
                  {template.bypasses.length > 0 &&
                    ` Not enforced against: ${template.bypasses.join(" ")}`}
                </p>
              )}
            </div>
          );
        })}
        {unused.length > 0 && (
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            onClick={() => set({ rules: [...value.rules, freshRule(unused[0]!, "required")] })}
          >
            Add rule
          </Button>
        )}
      </fieldset>
    </fieldset>
  );
}

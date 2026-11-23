import { cn } from "@/lib/utils";
import type { CapabilitiesOut, UsedByOut } from "../api/generated/coralApi";

const CAPABILITY_LABELS: Readonly<Record<keyof CapabilitiesOut, string>> = {
  tool_gating: "tool gating",
  fs_read_only: "read-only files",
  steering: "steering",
  usage_reporting: "usage reporting",
};

const SUPPORT_CLASS: Readonly<Record<CapabilitiesOut[keyof CapabilitiesOut], string>> = {
  supported: "border-success/40 text-foreground",
  unsupported: "border-destructive/40 text-muted-foreground line-through",
  unknown: "border-dashed border-border text-muted-foreground",
};

/** What a profile's harness can do; `unknown` is never shown as supported. */
export function CapabilityChips({ capabilities }: { capabilities: CapabilitiesOut }) {
  return (
    <ul className="flex flex-wrap gap-1" aria-label="Capabilities">
      {(Object.keys(CAPABILITY_LABELS) as (keyof CapabilitiesOut)[]).map((key) => {
        const support = capabilities[key];
        return (
          <li
            key={key}
            data-support={support}
            className={cn("rounded-full border px-2 py-0.5 text-xs", SUPPORT_CLASS[support])}
          >
            {`${CAPABILITY_LABELS[key]}: ${support}`}
          </li>
        );
      })}
    </ul>
  );
}

const count = (n: number, noun: string) => `${n} ${noun}${n === 1 ? "" : "s"}`;

/** Where a profile is in use: workflows that name it and unfinished runs pinned to it. */
export function UsedBy({ usedBy }: { usedBy: UsedByOut }) {
  return (
    <span className="text-muted-foreground text-xs">
      {`Used by ${count(usedBy.workflows, "workflow")}, ${count(usedBy.running_runs, "running run")}`}
    </span>
  );
}

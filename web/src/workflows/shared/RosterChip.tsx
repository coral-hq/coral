import { BotIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { harnessLabel } from "./harnessLabel";

export interface RosterChipProps {
  /** The roster profile that works on the step. */
  profile: string;
  /** The step's harness id; `null` for the workspace default. */
  harness: string | null;
  className?: string;
}

/** One agent of a step: its roster profile and the harness it runs on. */
export function RosterChip({ profile, harness, className }: RosterChipProps) {
  const label = harnessLabel(harness);
  return (
    <span
      data-testid="roster-chip"
      className={cn(
        "inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-xs",
        className,
      )}
    >
      <BotIcon aria-hidden className="size-3 shrink-0 text-muted-foreground" />
      <span className="truncate text-foreground">{profile}</span>
      {/* Read as one phrase; the flex gap, not this space, spaces it on screen. */}
      {label !== null && " "}
      {label !== null && <span className="shrink-0 text-muted-foreground">· {label}</span>}
    </span>
  );
}

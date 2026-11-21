import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { runStatus, type RunStatusTone } from "./runStatus";

const TONE_CLASS: Record<RunStatusTone, string> = {
  blue: "bg-status-blue/12 text-status-blue",
  yellow: "bg-status-yellow/12 text-status-yellow",
  green: "bg-status-green/12 text-status-green",
  red: "bg-status-red/12 text-status-red",
  gray: "bg-status-gray/12 text-status-gray",
};

export interface RunStatusPillProps {
  status: string;
  pauseReason: string | null;
  /** The view's open gates; `null` where no view is known (the runs list). */
  openGates: readonly string[] | null;
  className?: string;
}

/** A run's status as a pill: "Starting", "Needs you", "Paused: <reason>", … */
export function RunStatusPill({ status, pauseReason, openGates, className }: RunStatusPillProps) {
  const { kind, text, tone } = runStatus(status, pauseReason, openGates);
  return (
    <Badge variant="secondary" data-status={kind} className={cn(TONE_CLASS[tone], className)}>
      {text}
    </Badge>
  );
}

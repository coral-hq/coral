import { useEffect, useState, type ReactNode, type Ref } from "react";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { formatSessionCostUsd, formatTokenCount } from "@/lib/formatCost";
import { formatRunDuration } from "@/lib/scheduleText";
import { cn } from "@/lib/utils";
import type { RunSpend } from "../api/generated/coralApi";
import { RunStatusPill } from "../shared/RunStatusPill";

// The run page's header: the run's title, its status pill and the connection notice in one
// polite live region, how long it has run, what it has spent so far (never a cap), and the
// run's actions.

const UNKNOWN = "—";
/** Elapsed time shows seconds, so it ticks every second until the run ends. */
export const ELAPSED_TICK_MS = 1_000;

const nowSeconds = () => Math.floor(Date.now() / 1000);

/** How long the run has run: to its end, or to now, ticking while it is unfinished. */
function useElapsedText(createdAt: number | null, finishedAt: number | null): string {
  const ticking = createdAt !== null && finishedAt === null;
  const [now, setNow] = useState(nowSeconds);
  useEffect(() => {
    if (!ticking) return undefined;
    setNow(nowSeconds());
    const timer = setInterval(() => setNow(nowSeconds()), ELAPSED_TICK_MS);
    return () => clearInterval(timer);
  }, [ticking]);
  return formatRunDuration(createdAt, finishedAt ?? now) ?? UNKNOWN;
}

/** The spend figure: dollars, "at least" dollars while models are unpriced, else tokens. */
export function spendText(spend: RunSpend | null | undefined): string {
  if (spend == null) return UNKNOWN;
  if (spend.usd === null) return `${formatTokenCount(spend.tokens.total)} tokens`;
  const usd = formatSessionCostUsd(spend.usd);
  return spend.unpriced_models.length > 0 ? `at least ${usd}` : usd;
}

export interface RunHeaderBarProps {
  title: string;
  status: string;
  pauseReason: string | null;
  /** The view's open gates; `null` where no view is known. */
  openGates: readonly string[] | null;
  /** The status is the detail's, shown until the stream's first frame. */
  provisional: boolean;
  /** Epoch seconds; `null` until the detail loads. */
  createdAt: number | null;
  finishedAt: number | null;
  /** `undefined` until the detail loads. */
  spend: RunSpend | null | undefined;
  /** What the page says about its live updates, if anything. */
  notice: string | null;
  actions?: ReactNode;
  /** The status region, which the page focuses when it recovers from a dead end. */
  statusRef?: Ref<HTMLDivElement>;
}

export function RunHeaderBar({
  title,
  status,
  pauseReason,
  openGates,
  provisional,
  createdAt,
  finishedAt,
  spend,
  notice,
  actions,
  statusRef,
}: RunHeaderBarProps) {
  const elapsed = useElapsedText(createdAt, finishedAt);
  return (
    <CoralPageHeader
      title={title}
      titleAccessory={
        <div
          ref={statusRef}
          tabIndex={-1}
          role="status"
          aria-live="polite"
          data-testid="run-status"
          className="flex flex-wrap items-center gap-2 outline-none"
        >
          <span
            data-testid="run-status-pill"
            data-provisional={provisional}
            className={cn(provisional && "opacity-60")}
          >
            <RunStatusPill status={status} pauseReason={pauseReason} openGates={openGates} />
            {provisional && <span className="sr-only"> (not live yet)</span>}
          </span>
          {notice !== null && <span className="text-sm text-muted-foreground">{notice}</span>}
        </div>
      }
      description={
        <span className="flex flex-wrap gap-x-4 gap-y-1">
          <span data-testid="run-elapsed">
            Elapsed <span className="text-foreground tabular-nums">{elapsed}</span>
          </span>
          <span data-testid="run-spend">
            Spend so far (estimate){" "}
            <span className="text-foreground tabular-nums">{spendText(spend)}</span>
          </span>
        </span>
      }
      actions={actions}
    />
  );
}

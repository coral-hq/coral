import { useQuery } from "@tanstack/react-query";
import { TriangleAlertIcon } from "lucide-react";
import { useEffect, useId, useRef, useState, type Ref } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { CliCommandBlock, renderTextWithInlineCode } from "@/shell/CliCommandBlock";
import type { RunOutcome } from "../../api/generated/coralApi";
import { getRunOutcome, isRunNotFound, retryRunRead, runOutcomeQueryKey } from "../../api/runsApi";
import { useCoralScope } from "../../shared/viewerScope";
import {
  checkoutHint,
  checkoutNote,
  diffNote,
  diffSummary,
  ESCAPED_PATH_LABEL,
  ESCAPED_PATHS_TEXT,
  holdsEscape,
  OUTCOME_LOAD_FAILED_TEXT,
  OUTCOME_NOT_AVAILABLE_TEXT,
  pathsShown,
  shortCommit,
} from "./outcomeText";

// A finished run's outcome: its branch, base and head, the diff's summary and paths, and
// the server's commands to check the branch out and to open the worktree. Commands and
// paths are shown exactly as the server sent them, left to right and isolated from the
// text around them; the panel never builds a command. Mount it only for a finished run.

/** Left to right, isolated: right-to-left text nearby cannot reorder what is read or copied. */
const LTR_ISOLATED = "[unicode-bidi:isolate]";

export function OutcomePanel({ runId }: { runId: string }) {
  const headingId = useId();
  const { scope, ready } = useCoralScope();
  const outcome = useQuery({
    queryKey: runOutcomeQueryKey(scope, runId),
    queryFn: ({ signal }) => getRunOutcome(runId, signal),
    enabled: ready,
    retry: retryRunRead,
  });
  const headingRef = useRef<HTMLHeadingElement>(null);
  // The one Retry the panel shows, if any: the load failure's or the note's.
  const retryRef = useRef<HTMLButtonElement>(null);
  // Set by Retry until its read ends; a read waiting for the network has not ended.
  const [retryPending, setRetryPending] = useState(false);
  const retry = () => {
    setRetryPending(true);
    void outcome.refetch();
  };
  const { isFetching } = outcome;
  const reading = outcome.fetchStatus !== "idle";
  // Once Retry's read ends, focus left on the body (Retry gone, or blurred while disabled)
  // goes back to Retry while it is still offered, else to the panel's heading.
  useEffect(() => {
    if (!retryPending || reading) return;
    setRetryPending(false);
    const focused = document.activeElement;
    if (focused !== null && focused !== document.body) return;
    (retryRef.current ?? headingRef.current)?.focus();
  }, [retryPending, reading]);
  return (
    <section
      aria-labelledby={headingId}
      data-testid="run-outcome"
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
    >
      <h2
        id={headingId}
        ref={headingRef}
        tabIndex={-1}
        className="text-ui font-medium text-foreground outline-none"
      >
        Outcome
      </h2>
      {outcome.data ? (
        <OutcomeBody
          outcome={outcome.data}
          retrying={isFetching}
          onRetry={retry}
          retryRef={retryRef}
        />
      ) : outcome.error ? (
        <div className="flex flex-col items-start gap-2">
          <p data-testid="run-outcome-state" className="text-ui text-muted-foreground">
            {isRunNotFound(outcome.error) ? OUTCOME_NOT_AVAILABLE_TEXT : OUTCOME_LOAD_FAILED_TEXT}
          </p>
          {!isRunNotFound(outcome.error) && (
            <RetryButton retrying={isFetching} onRetry={retry} buttonRef={retryRef} />
          )}
        </div>
      ) : (
        <Spinner
          role="img"
          className="size-4 text-muted-foreground"
          aria-label="Loading the run’s outcome"
        />
      )}
    </section>
  );
}

interface RetryProps {
  retrying: boolean;
  onRetry: () => void;
}

function RetryButton({
  retrying,
  onRetry,
  buttonRef,
}: RetryProps & { buttonRef: Ref<HTMLButtonElement> }) {
  return (
    <Button
      ref={buttonRef}
      variant="outline"
      size="sm"
      onClick={onRetry}
      disabled={retrying}
      componentId="workflows.run.outcome.retry"
    >
      Retry
    </Button>
  );
}

function OutcomeBody({
  outcome,
  retrying,
  onRetry,
  retryRef,
}: RetryProps & { outcome: RunOutcome; retryRef: Ref<HTMLButtonElement> }) {
  const { branch, base_commit: base, head_commit: head, diff, checkout } = outcome;
  const note = diffNote(outcome.diff_unavailable);
  const shown = diff ? pathsShown(diff) : null;
  // Two long paths can be cut to the same text: the second is keyed as its second copy.
  const seen = new Map<string, number>();
  const listed = (shown?.paths ?? []).map((path) => {
    const copy = (seen.get(path) ?? 0) + 1;
    seen.set(path, copy);
    return { path, key: `${copy}:${path}`, escaped: holdsEscape(path) };
  });
  return (
    <>
      {branch !== null && (
        <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-ui">
          <dt className="text-muted-foreground">Branch</dt>
          <dd>
            <code
              data-testid="run-outcome-branch"
              dir="ltr"
              className={`break-all font-mono text-sm ${LTR_ISOLATED}`}
            >
              {branch}
            </code>
          </dd>
          {base !== null && (
            <>
              <dt className="text-muted-foreground">Commits</dt>
              <dd
                data-testid="run-outcome-commits"
                title={head === null ? base : `${base} → ${head}`}
                className="font-mono text-sm"
              >
                {head === null
                  ? `Base ${shortCommit(base)}`
                  : `${shortCommit(base)} → ${shortCommit(head)}`}
              </dd>
            </>
          )}
        </dl>
      )}
      {diff && shown && (
        <div className="flex flex-col gap-1">
          <p data-testid="run-outcome-summary" className="text-ui">
            {diffSummary(diff)}
          </p>
          {shown.paths.length > 0 && (
            <>
              <ul
                data-testid="run-outcome-paths"
                dir="ltr"
                className={`flex flex-col font-mono text-sm text-muted-foreground ${LTR_ISOLATED}`}
              >
                {listed.map(({ path, key, escaped }) => (
                  <li key={key} className="break-all" data-escaped={escaped ? "true" : undefined}>
                    {escaped && (
                      <TriangleAlertIcon
                        role="img"
                        aria-label={ESCAPED_PATH_LABEL}
                        className="mr-1 inline size-3.5 align-[-2px] text-status-yellow"
                      />
                    )}
                    {path}
                  </li>
                ))}
              </ul>
              {shown.more > 0 && (
                <p data-testid="run-outcome-more" className="text-sm text-muted-foreground">
                  and {shown.more} more
                </p>
              )}
              {listed.some(({ escaped }) => escaped) && (
                <p data-testid="run-outcome-escapes" className="text-sm text-muted-foreground">
                  {ESCAPED_PATHS_TEXT}
                </p>
              )}
            </>
          )}
        </div>
      )}
      {note && (
        <div className="flex flex-col items-start gap-2">
          <p data-testid="run-outcome-note" className="text-ui text-muted-foreground">
            {note.text}
          </p>
          {note.retry && <RetryButton retrying={retrying} onRetry={onRetry} buttonRef={retryRef} />}
        </div>
      )}
      {checkout.command !== null || checkout.worktree_command !== null ? (
        <div className="flex flex-col gap-2">
          {checkout.command !== null && (
            <>
              <div data-testid="run-outcome-checkout" dir="ltr" className={LTR_ISOLATED}>
                <CliCommandBlock command={checkout.command} testIdPrefix="run-outcome-checkout" />
              </div>
              <p data-testid="run-outcome-hint" className="text-sm text-muted-foreground">
                {renderTextWithInlineCode(checkoutHint(outcome.diff_unavailable))}
              </p>
            </>
          )}
          {checkout.worktree_command !== null && (
            <div data-testid="run-outcome-worktree" dir="ltr" className={LTR_ISOLATED}>
              <CliCommandBlock
                command={checkout.worktree_command}
                testIdPrefix="run-outcome-worktree"
              />
            </div>
          )}
        </div>
      ) : (
        <p data-testid="run-outcome-checkout-note" className="text-ui text-muted-foreground">
          {renderTextWithInlineCode(checkoutNote(checkout.unavailable ?? "no_worktree", branch))}
        </p>
      )}
    </>
  );
}

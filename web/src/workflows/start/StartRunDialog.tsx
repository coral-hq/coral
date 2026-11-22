import { useEffect, useRef, useState, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Spinner } from "@/components/ui/spinner";
import { showToast } from "@/components/ui/toast";
import { useHosts } from "@/hooks/useHosts";
import { randomUUID } from "@/lib/randomUUID";
import { Link, useNavigate } from "@/lib/routing";
import { ApiError } from "@/lib/sessionsApi";
import { WorkspacePickerDialog } from "@/shell/WorkspacePickerDialog";
import type { StartRunRequest } from "../api/generated/coralApi";
import {
  CoralRequestError,
  MAX_RETRY_AFTER_MS,
  preflightQueryKey,
  preflightRun,
  runsListPrefixKey,
  startRun,
} from "../api/runsApi";
import { runPath } from "../nav/coralPaths";
import { useCoralScope } from "../shared/viewerScope";
import { PreflightList } from "./PreflightList";

// Starts a workflow on a host's repository through `POST /v1/coral/runs`. The start key
// makes the POST idempotent: a retry of the same inputs replays the run it started, and a
// new opening or another host or folder gets a new key. The inputs are locked while a start
// is in flight. A start that lands after the dialog closed leaves the person where they are,
// with a notice linking to the run. Preflight runs once a host is chosen and gates Start.

const GENERIC_REFUSAL = "Couldn't start the run. Try again.";

export interface StartRunDialogProps {
  /** The stored definition's id, which the start names. */
  workflowId: string;
  workflowKey: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** The text for a refused start: by status and Coral's code, else the generic retry text. */
function startRefusalText(error: unknown): string {
  if (!(error instanceof ApiError)) return GENERIC_REFUSAL;
  const coral = error instanceof CoralRequestError;
  switch (error.status) {
    case 400:
      return error.code === "not_a_git_repo"
        ? "That folder isn't the root of a git repository."
        : GENERIC_REFUSAL;
    case 403:
      return "You can't start runs on this host.";
    case 404:
      return "This workflow no longer exists.";
    case 409:
      // A conflicting start key or a worktree the host could not make: the server says which.
      return coral && error.message ? error.message : GENERIC_REFUSAL;
    case 422:
      return coral && error.code === "not_runnable"
        ? `This workflow can't run yet: ${error.message}`
        : GENERIC_REFUSAL;
    case 503:
      return error.code === "host_offline"
        ? "The host is offline."
        : "The server is busy; try again.";
    default:
      return GENERIC_REFUSAL;
  }
}

/** How long a refused start holds Start: a busy server's `Retry-After`, capped. */
function startHoldMs(error: unknown): number {
  if (!(error instanceof ApiError) || error.status !== 503 || error.retryAfterMs === null) return 0;
  return Math.min(error.retryAfterMs, MAX_RETRY_AFTER_MS);
}

/**
 * The start key for what the dialog would start now: kept while the inputs and the
 * opening stay the same, so a retry replays; new when the dialog opens or an input changes.
 */
function useStartKey(open: boolean, inputs: string): string {
  const [held, setHeld] = useState(() => ({ open, inputs, key: randomUUID() }));
  if (held.open === open && held.inputs === inputs) return held.key;
  const renew = (open && !held.open) || held.inputs !== inputs;
  const next = { open, inputs, key: renew ? randomUUID() : held.key };
  setHeld(next);
  return next.key;
}

export function StartRunDialog({
  workflowId,
  workflowKey,
  open,
  onOpenChange,
}: StartRunDialogProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { scope } = useCoralScope();
  const hosts = useHosts({ enabled: open });
  const [hostId, setHostId] = useState<string | null>(null);
  const [repoPath, setRepoPath] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [holdMs, setHoldMs] = useState(0);
  const startKey = useStartKey(open, JSON.stringify([workflowId, hostId, repoPath]));
  // The mutation's pending state renders after the click, so a second click would post again.
  const posting = useRef(false);
  // Open and mounted: where a landing start may still take the person to its run.
  const showing = useRef(open);

  const preflight = useQuery({
    queryKey: preflightQueryKey(scope, workflowId, hostId ?? ""),
    queryFn: ({ signal }) => preflightRun({ workflow_id: workflowId, host_id: hostId! }, signal),
    enabled: open && hostId !== null,
  });

  const start = useMutation({
    mutationFn: (request: StartRunRequest) => startRun(request),
    onSuccess: ({ run_id }) => {
      // The runs history lists the new run the next time it shows.
      void queryClient.invalidateQueries({ queryKey: runsListPrefixKey(scope) });
      if (!showing.current) {
        showToast(runStartedNotice(run_id));
        return;
      }
      onOpenChange(false);
      navigate(runPath(run_id));
    },
    onError: (error) => {
      if (showing.current) setHoldMs(startHoldMs(error));
    },
    onSettled: () => {
      posting.current = false;
    },
  });
  const resetStart = start.reset;

  useEffect(() => {
    showing.current = open;
    // Each opening starts clean: no refusal or hold from the last one, even one that landed
    // while the dialog was closed.
    if (!posting.current) {
      resetStart();
      setHoldMs(0);
    }
    return () => {
      showing.current = false;
    };
  }, [open, resetStart]);

  useEffect(() => {
    if (holdMs === 0) return undefined;
    const timer = setTimeout(() => setHoldMs(0), holdMs);
    return () => clearTimeout(timer);
  }, [holdMs]);

  const onlineHosts = (hosts.data ?? []).filter((host) => host.status === "online");
  const request: StartRunRequest | null =
    hostId && repoPath
      ? { workflow_id: workflowId, start_key: startKey, host_id: hostId, repo_path: repoPath }
      : null;
  // Locked while a start is in flight, so its answer always belongs to the inputs shown.
  const locked = start.isPending;
  const preflightOk = preflight.data?.ok === true;
  const preflightBlocking =
    hostId !== null && (preflight.isPending || preflight.isError || !preflightOk);
  // A refusal of other inputs says nothing about these; the same inputs keep their hold.
  const changeInputs = (nextHostId: string | null, nextRepoPath: string | null) => {
    if (posting.current || (nextHostId === hostId && nextRepoPath === repoPath)) return;
    setHostId(nextHostId);
    setRepoPath(nextRepoPath);
    setHoldMs(0);
    start.reset();
  };

  return (
    <>
      <Dialog open={open} onOpenChange={onOpenChange}>
        <DialogContent data-testid="start-run-dialog">
          <DialogHeader>
            <DialogTitle>Start run</DialogTitle>
            <DialogDescription>Pick a host and folder to run {workflowKey} in.</DialogDescription>
          </DialogHeader>

          <section className="flex flex-col gap-2">
            <h3 className="font-medium text-foreground text-ui">Host</h3>
            {hosts.isPending ? (
              <Spinner className="size-4 text-muted-foreground" aria-label="Loading hosts" />
            ) : onlineHosts.length === 0 ? (
              <p className="text-muted-foreground text-ui">No online hosts.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {onlineHosts.map((host) => (
                  <Button
                    key={host.host_id}
                    variant={host.host_id === hostId ? "default" : "outline"}
                    size="sm"
                    aria-pressed={host.host_id === hostId}
                    disabled={locked}
                    onClick={() => changeInputs(host.host_id, null)}
                  >
                    {host.name}
                  </Button>
                ))}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-2">
            <h3 className="font-medium text-foreground text-ui">Repository folder</h3>
            <div className="flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate text-muted-foreground text-xs">
                {repoPath ?? "None selected"}
              </code>
              <Button
                variant="outline"
                size="sm"
                disabled={!hostId || locked}
                onClick={() => setPickerOpen(true)}
              >
                Choose folder
              </Button>
            </div>
          </section>

          {hostId !== null && (
            <section className="flex flex-col gap-2">
              <h3 className="font-medium text-foreground text-ui">Preflight</h3>
              {preflight.isPending ? (
                <Spinner className="size-4 text-muted-foreground" aria-label="Checking host" />
              ) : preflight.isError ? (
                <p className="text-destructive text-ui" role="alert">
                  Couldn't check this host.{" "}
                  <Button
                    variant="link"
                    className="h-auto p-0 text-destructive underline"
                    onClick={() => void preflight.refetch()}
                  >
                    Retry
                  </Button>
                </p>
              ) : preflight.data != null ? (
                <>
                  <PreflightList items={preflight.data.items} />
                  <p className="text-muted-foreground text-xs">
                    About {preflight.data.estimate.sessions} sessions for one pass.
                  </p>
                </>
              ) : null}
            </section>
          )}

          {start.isError && (
            <p className="text-destructive text-ui" role="alert">
              {startRefusalText(start.error)}
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              componentId="coral.start_run.submit"
              loading={start.isPending}
              disabled={request === null || holdMs > 0 || preflightBlocking}
              onClick={() => {
                if (request === null || posting.current || preflightBlocking) return;
                posting.current = true;
                start.mutate(request);
              }}
            >
              Start run
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <WorkspacePickerDialog
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        hostId={hostId}
        onConfirm={(path) => changeInputs(hostId, path)}
        title="Select repository folder"
        description="Choose the repository the workflow will run in."
      />
    </>
  );
}

/** The notice for a start that landed after the dialog closed. */
function runStartedNotice(runId: string): ReactNode {
  return (
    <span>
      The run started.{" "}
      <Link
        to={runPath(runId)}
        componentId="coral.start_run.open_started"
        className="underline underline-offset-2"
      >
        Open run
      </Link>
    </span>
  );
}

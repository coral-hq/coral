import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import {
  deleteWorkflowCase,
  listWorkflowCases,
  shouldRetryWorkflows,
  workflowCasesQueryKey,
} from "../api/client";
import type { SavedCaseOut, SimScript } from "../api/generated/coralApi";

const STATUS_TEXT: Readonly<Record<NonNullable<SavedCaseOut["last_result"]>, string>> = {
  passed: "Passed",
  failed: "Failed",
  error: "Error",
};

export function SavedCases({
  workflowId,
  onRun,
}: {
  workflowId: string;
  onRun: (script: SimScript) => void;
}) {
  const cases = useQuery({
    queryKey: workflowCasesQueryKey(workflowId),
    retry: shouldRetryWorkflows,
    queryFn: ({ signal }) => listWorkflowCases(workflowId, signal),
  });

  return (
    <section
      aria-label="Saved cases"
      className="flex max-h-60 flex-col gap-2 overflow-auto border-border border-t px-6 py-3 text-ui"
      data-testid="saved-cases"
    >
      <h2 className="font-medium text-foreground text-ui">Saved cases</h2>
      {cases.isPending ? (
        <Spinner className="size-4 text-muted-foreground" aria-label="Loading cases" />
      ) : cases.isError ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-muted-foreground">Couldn't load saved cases.</p>
          <Button variant="outline" size="sm" onClick={() => void cases.refetch()}>
            Retry
          </Button>
        </div>
      ) : cases.data.length === 0 ? (
        <p className="text-muted-foreground">
          No saved cases yet. Simulate the workflow and save the result as a case.
        </p>
      ) : (
        <ul className="flex flex-col divide-y divide-border">
          {cases.data.map((saved) => (
            <SavedCaseRow key={saved.id} workflowId={workflowId} saved={saved} onRun={onRun} />
          ))}
        </ul>
      )}
    </section>
  );
}

function SavedCaseRow({
  workflowId,
  saved,
  onRun,
}: {
  workflowId: string;
  saved: SavedCaseOut;
  onRun: (script: SimScript) => void;
}) {
  const queryClient = useQueryClient();
  const remove = useMutation({
    mutationFn: () => deleteWorkflowCase(workflowId, saved.id),
    onSettled: () =>
      void queryClient.invalidateQueries({ queryKey: workflowCasesQueryKey(workflowId) }),
  });
  const result = saved.last_result;
  return (
    <li className="flex flex-col gap-1 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="min-w-0 flex-1 truncate text-foreground">{saved.name}</span>
        <Badge variant={result === "failed" || result === "error" ? "destructive" : "secondary"}>
          {result === null ? "Not run" : STATUS_TEXT[result]}
        </Badge>
        <Button
          variant="outline"
          size="sm"
          componentId="coral.cases.run"
          aria-label={`Run ${saved.name}`}
          onClick={() => onRun(saved.script)}
        >
          Run
        </Button>
        <Button
          variant="ghost"
          size="sm"
          componentId="coral.cases.delete"
          aria-label={`Delete ${saved.name}`}
          loading={remove.isPending}
          onClick={() => remove.mutate()}
        >
          Delete
        </Button>
      </div>
      {(result === "failed" || result === "error") &&
        saved.mismatches.map((line) => (
          <p key={line} className="text-muted-foreground text-xs">
            {line}
          </p>
        ))}
      {remove.isError && (
        <p className="text-destructive text-xs">Couldn't delete the case. Try again.</p>
      )}
    </li>
  );
}

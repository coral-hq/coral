import { Suspense, lazy, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { useParams } from "@/lib/routing";
import {
  WORKFLOWS_QUERY_KEY,
  getWorkflowByKey,
  shouldRetryWorkflows,
  saveWorkflow,
  workflowQueryKey,
} from "../api/client";
import type { WorkflowDetail } from "../api/workflowTypes";
import { FlowCanvas } from "../canvas/FlowCanvas";
import { StartRunDialog } from "../start/StartRunDialog";
import { diagnosticsFromValidate, markersFromDiagnostics } from "./markers";
import { useValidateLoop } from "./useValidateLoop";

// Monaco is heavy; load it only once an editor actually opens.
const YamlPane = lazy(() => import("./YamlPane").then((m) => ({ default: m.YamlPane })));

export function WorkflowEditorPage() {
  const { workflowKey = "" } = useParams<{ workflowKey: string }>();
  const workflow = useQuery<WorkflowDetail, Error>({
    queryKey: workflowQueryKey(workflowKey),
    retry: shouldRetryWorkflows,
    queryFn: ({ signal }) => getWorkflowByKey(workflowKey, signal),
  });

  if (workflow.isPending) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }
  if (workflow.isError) {
    return (
      <div
        className="flex flex-1 flex-col items-center justify-center gap-3 px-6 text-center"
        data-testid="workflow-editor-error"
      >
        <h1 className="font-medium text-foreground text-lg">Couldn't open workflow</h1>
        <p className="text-muted-foreground text-ui">{workflow.error.message}</p>
        <Button variant="outline" onClick={() => void workflow.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  return (
    <EditorSurface
      workflowKey={workflowKey}
      name={workflow.data.name}
      initialYaml={workflow.data.yaml}
      initialCompiled={workflow.data.compiled}
    />
  );
}

function EditorSurface({
  workflowKey,
  name,
  initialYaml,
  initialCompiled,
}: {
  workflowKey: string;
  name: string;
  initialYaml: string;
  initialCompiled: Parameters<typeof useValidateLoop>[1];
}) {
  const queryClient = useQueryClient();
  const [yaml, setYaml] = useState(initialYaml);
  const [startOpen, setStartOpen] = useState(false);
  const validation = useValidateLoop(yaml, initialCompiled);
  const diagnostics = useMemo(
    () => diagnosticsFromValidate(validation.response),
    [validation.response],
  );
  const markers = useMemo(() => markersFromDiagnostics(diagnostics), [diagnostics]);
  const dirty = yaml !== initialYaml;

  const save = useMutation({
    mutationFn: () => saveWorkflow(yaml),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WORKFLOWS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: workflowQueryKey(workflowKey) });
    },
  });

  const runnable = validation.response?.runnable === true;
  const hasErrors = diagnostics.some((diagnostic) => diagnostic.severity === "error");

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="workflow-editor">
      <CoralPageHeader
        variant="fullBleed"
        title={name}
        description={workflowKey}
        actions={
          <div className="flex items-center gap-2">
            {validation.isValidating && (
              <span className="text-muted-foreground text-xs">Validating…</span>
            )}
            <Button
              variant="outline"
              componentId="coral.editor.save"
              disabled={!dirty || hasErrors || save.isPending}
              onClick={() => save.mutate()}
            >
              Save
            </Button>
            <Button
              componentId="coral.editor.start_run"
              disabled={dirty || !runnable}
              onClick={() => setStartOpen(true)}
            >
              Start Run
            </Button>
          </div>
        }
      />
      <div className="flex min-h-0 flex-1 flex-col gap-3 px-6 pb-4 md:flex-row">
        <div className="min-h-[320px] min-w-0 flex-1 overflow-hidden rounded-lg border border-border">
          <Suspense fallback={<EditorFallback />}>
            <YamlPane value={yaml} onChange={setYaml} markers={markers} />
          </Suspense>
        </div>
        <div className="min-h-[320px] min-w-0 flex-1 overflow-hidden rounded-lg border border-border">
          <FlowCanvas compiled={validation.compiled} />
        </div>
      </div>
      <ProblemList diagnostics={diagnostics} error={validation.error} saveError={save.error} />
      <StartRunDialog workflowKey={workflowKey} open={startOpen} onOpenChange={setStartOpen} />
    </div>
  );
}

function ProblemList({
  diagnostics,
  error,
  saveError,
}: {
  diagnostics: ReturnType<typeof diagnosticsFromValidate>;
  error: Error | null;
  saveError: Error | null;
}) {
  const failure = error ?? saveError;
  if (diagnostics.length === 0 && !failure) return null;
  return (
    <ul
      className="max-h-40 overflow-auto border-border border-t px-6 py-2 text-ui"
      data-testid="problem-list"
    >
      {failure && <li className="text-destructive">{failure.message}</li>}
      {diagnostics.map((diagnostic) => (
        <li key={diagnostic.key} className="flex items-baseline gap-2 py-0.5">
          <Badge variant={diagnostic.severity === "error" ? "destructive" : "secondary"}>
            {diagnostic.rule ?? diagnostic.severity}
          </Badge>
          <span className="text-foreground">{diagnostic.message}</span>
          {diagnostic.range && (
            <span className="text-muted-foreground text-xs">
              line {diagnostic.range.start_line}
            </span>
          )}
        </li>
      ))}
    </ul>
  );
}

function EditorFallback() {
  return (
    <div className="flex size-full items-center justify-center">
      <Spinner className="size-5 text-muted-foreground" aria-label="Loading editor" />
    </div>
  );
}

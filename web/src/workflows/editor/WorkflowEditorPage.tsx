import { Suspense, lazy, useId, useMemo, useRef, useState } from "react";
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
  workflowCasesQueryKey,
  workflowQueryKey,
} from "../api/client";
import type { SimScript } from "../api/generated/coralApi";
import { CORAL_SUB_FEATURE } from "../api/types";
import type { WorkflowDetail } from "../api/workflowTypes";
import { FlowCanvas } from "../canvas/FlowCanvas";
import { isCoralAvailable, useCoralInfo } from "../gate/useCoralInfo";
import { ProfilePicker } from "../profiles/ProfilePicker";
import { SavedCases } from "../simulate/SavedCases";
import { SimulatePanel } from "../simulate/SimulatePanel";
import { useSimulation } from "../simulate/useSimulation";
import { StartRunDialog } from "../start/StartRunDialog";
import { diagnosticsFromValidate, markersFromDiagnostics } from "./markers";
import { useValidateLoop } from "./useValidateLoop";
import type { YamlEditor } from "./YamlPane";

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
      workflowId={workflow.data.id}
      workflowKey={workflowKey}
      name={workflow.data.name}
      initialYaml={workflow.data.yaml}
      initialCompiled={workflow.data.compiled}
    />
  );
}

function EditorSurface({
  workflowId,
  workflowKey,
  name,
  initialYaml,
  initialCompiled,
}: {
  workflowId: string;
  workflowKey: string;
  name: string;
  initialYaml: string;
  initialCompiled: Parameters<typeof useValidateLoop>[1];
}) {
  const queryClient = useQueryClient();
  const [yaml, setYaml] = useState(initialYaml);
  const [startOpen, setStartOpen] = useState(false);
  const [simulateOpen, setSimulateOpen] = useState(false);
  const simulatePanelId = useId();
  const simulateButtonRef = useRef<HTMLButtonElement>(null);
  const editorRef = useRef<YamlEditor | null>(null);
  const profilesOn = isCoralAvailable(useCoralInfo().data, CORAL_SUB_FEATURE.profilesDesk);
  const validation = useValidateLoop(yaml, initialCompiled);
  const diagnostics = useMemo(
    () => diagnosticsFromValidate(validation.response),
    [validation.response],
  );
  const markers = useMemo(() => markersFromDiagnostics(diagnostics), [diagnostics]);
  const simulation = useSimulation(yaml, simulateOpen);
  const dirty = yaml !== initialYaml;

  const save = useMutation({
    mutationFn: () => saveWorkflow(yaml),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: WORKFLOWS_QUERY_KEY });
      void queryClient.invalidateQueries({ queryKey: workflowQueryKey(workflowKey) });
      void queryClient.invalidateQueries({ queryKey: workflowCasesQueryKey(workflowId) });
    },
  });

  // The ref replaces the selection at the cursor; Monaco's change event updates `yaml`.
  const insertProfile = (ref: string) => {
    const editor = editorRef.current;
    const selection = editor?.getSelection();
    if (!editor || !selection) return;
    editor.executeEdits("coral.insert-profile", [{ range: selection, text: ref }]);
    editor.focus();
  };

  const runnable = validation.response?.runnable === true;
  const hasErrors = diagnostics.some((diagnostic) => diagnostic.severity === "error");
  // The simulated run paints only the graph it ran on; once the YAML changes, the canvas
  // follows the YAML again with no overlay.
  const showSimulated = simulateOpen && !simulation.stale && simulation.overlay !== null;
  // The panel's Close removes the focused control; focus goes back to the button that opened it.
  const closeSimulate = () => {
    setSimulateOpen(false);
    simulateButtonRef.current?.focus();
  };
  const runCase = (script: SimScript) => {
    simulation.runScript(script);
    setSimulateOpen(true);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="workflow-editor">
      <CoralPageHeader
        variant="fullBleed"
        title={name}
        description={workflowKey}
        actions={
          <div className="flex items-center gap-2">
            {profilesOn && <ProfilePicker onPick={insertProfile} />}
            {validation.isValidating && (
              <span className="text-muted-foreground text-xs">Validating…</span>
            )}
            <Button
              ref={simulateButtonRef}
              variant="outline"
              componentId="coral.editor.simulate"
              aria-expanded={simulateOpen}
              aria-controls={simulateOpen ? simulatePanelId : undefined}
              disabled={hasErrors && !simulateOpen}
              onClick={() => setSimulateOpen((open) => !open)}
            >
              Simulate
            </Button>
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
            <YamlPane
              value={yaml}
              onChange={setYaml}
              markers={markers}
              onEditorReady={(editor) => {
                editorRef.current = editor;
              }}
            />
          </Suspense>
        </div>
        <div className="min-h-[320px] min-w-0 flex-1 overflow-hidden rounded-lg border border-border">
          <FlowCanvas
            compiled={showSimulated ? simulation.compiled : validation.compiled}
            overlay={showSimulated ? simulation.overlay : null}
          />
        </div>
      </div>
      {simulateOpen && (
        <SimulatePanel
          id={simulatePanelId}
          simulation={simulation}
          onClose={closeSimulate}
          workflowId={workflowId}
          dirty={dirty}
        />
      )}
      <SavedCases workflowId={workflowId} onRun={runCase} />
      <ProblemList diagnostics={diagnostics} error={validation.error} saveError={save.error} />
      <StartRunDialog
        workflowId={workflowId}
        workflowKey={workflowKey}
        open={startOpen}
        onOpenChange={setStartOpen}
      />
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

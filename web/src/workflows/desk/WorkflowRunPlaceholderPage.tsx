import { useParams } from "@/lib/routing";
import { DeskPlaceholderPage } from "./DeskPlaceholderPage";

export function WorkflowRunPlaceholderPage() {
  const { runId } = useParams<{ runId: string }>();
  return (
    <DeskPlaceholderPage title="Workflow run" detail={runId} testId="workflow-run-placeholder" />
  );
}

export function WorkflowEditorPlaceholderPage() {
  const { workflowKey } = useParams<{ workflowKey: string }>();
  return (
    <DeskPlaceholderPage title="Workflow" detail={workflowKey} testId="workflow-placeholder" />
  );
}

export function WorkflowSettingsPlaceholderPage() {
  return <DeskPlaceholderPage title="Workflow settings" testId="workflow-settings-placeholder" />;
}

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useNavigate, useSearchParams } from "@/lib/routing";
import {
  TEMPLATES_QUERY_KEY,
  WORKFLOWS_QUERY_KEY,
  createFromTemplate,
  listTemplates,
  listWorkflows,
  shouldRetryWorkflows,
} from "../api/client";
import type { TemplateOut } from "../api/generated/coralApi";
import type { WorkflowSummary } from "../api/workflowTypes";
import { CORAL_LABELS } from "../nav/labels";
import { workflowPath } from "../nav/coralPaths";
import { RunsTable } from "../runs/list/RunsTable";
import { ALL_RUNS, searchWithRunFilters } from "../runs/list/runFilters";

// The open tab rides `?tab=`, so a reload or a shared link keeps it; Your Workflows is the
// default and leaves the URL plain.
const TAB_PARAM = "tab";
const DESK_TABS = ["workflows", "runs", "templates"] as const;
type DeskTab = (typeof DESK_TABS)[number];
const DEFAULT_TAB: DeskTab = "workflows";

const isDeskTab = (value: string | null): value is DeskTab =>
  (DESK_TABS as readonly (string | null)[]).includes(value);

export function WorkflowsDeskPage() {
  const [search, setSearch] = useSearchParams();
  const requested = search.get(TAB_PARAM);
  const tab = isDeskTab(requested) ? requested : DEFAULT_TAB;
  // A new tab drops the runs filters, which belong to the Runs tab, and keeps other params.
  const openTab = (next: string) => {
    const params = searchWithRunFilters(search, ALL_RUNS);
    if (isDeskTab(next) && next !== DEFAULT_TAB) params.set(TAB_PARAM, next);
    else params.delete(TAB_PARAM);
    setSearch(params);
  };
  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid="workflows-desk"
    >
      <CoralPageHeader
        title={CORAL_LABELS.workflows}
        description="Multi-agent workflows you can run and inspect."
      />
      <Tabs value={tab} onValueChange={openTab} componentId="coral.desk.tabs">
        <TabsList variant="line">
          <TabsTrigger value="workflows">Your Workflows</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="templates">Templates</TabsTrigger>
        </TabsList>
        <TabsContent value="workflows">
          <YourWorkflows />
        </TabsContent>
        <TabsContent value="runs">
          <RunsTable />
        </TabsContent>
        <TabsContent value="templates">
          <Templates />
        </TabsContent>
      </Tabs>
    </PageScroll>
  );
}

function YourWorkflows() {
  const navigate = useNavigate();
  const workflows = useQuery({
    queryKey: WORKFLOWS_QUERY_KEY,
    retry: shouldRetryWorkflows,
    queryFn: ({ signal }) => listWorkflows(signal),
  });

  if (workflows.isPending) {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading workflows" />
      </div>
    );
  }
  if (workflows.isError) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-muted-foreground text-ui">Couldn't load workflows.</p>
        <Button variant="outline" onClick={() => void workflows.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  if (workflows.data.length === 0) {
    return (
      <div className="flex flex-col items-center gap-2 py-16 text-center">
        <h2 className="font-medium text-foreground text-lg">No workflows yet</h2>
        <p className="max-w-sm text-muted-foreground text-ui">
          Start from a template, or upload a workflow through the API or CLI and it will appear
          here.
        </p>
      </div>
    );
  }
  return (
    <ul className="flex flex-col divide-y divide-border" data-testid="workflow-list">
      {workflows.data.map((workflow: WorkflowSummary) => (
        <li key={workflow.id} className="flex items-center gap-3 py-3">
          <div className="flex min-w-0 flex-1 flex-col">
            <span className="truncate font-medium text-foreground text-ui">{workflow.name}</span>
            <span className="truncate text-muted-foreground text-xs">{workflow.workflow_key}</span>
          </div>
          {!workflow.runnable && <Badge variant="secondary">Draft</Badge>}
          <Button
            variant="outline"
            size="sm"
            componentId="coral.desk.open_workflow"
            onClick={() => navigate(workflowPath(workflow.workflow_key))}
          >
            Open
          </Button>
        </li>
      ))}
    </ul>
  );
}

function Templates() {
  const templates = useQuery({
    queryKey: TEMPLATES_QUERY_KEY,
    retry: shouldRetryWorkflows,
    queryFn: ({ signal }) => listTemplates(signal),
  });
  if (templates.isPending) {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading templates" />
      </div>
    );
  }
  if (templates.isError) {
    return (
      <div className="flex flex-col items-center gap-3 py-16 text-center">
        <p className="text-muted-foreground text-ui">Couldn't load templates.</p>
        <Button variant="outline" onClick={() => void templates.refetch()}>
          Retry
        </Button>
      </div>
    );
  }
  if (templates.data.length === 0) {
    return <p className="py-16 text-center text-muted-foreground text-ui">No templates yet.</p>;
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="template-list">
      {templates.data.map((template) => (
        <TemplateCard key={template.id} template={template} />
      ))}
    </div>
  );
}

function TemplateCard({ template }: { template: TemplateOut }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // The server makes a new copy under a free key each time, then the editor takes over.
  const useTemplate = useMutation({
    mutationFn: () => createFromTemplate(template.id),
    onSuccess: (saved) => {
      void queryClient.invalidateQueries({ queryKey: WORKFLOWS_QUERY_KEY });
      navigate(workflowPath(saved.workflow_key));
    },
  });
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border p-4">
      <h3 className="font-medium text-foreground text-ui">{template.name}</h3>
      <p className="flex-1 text-muted-foreground text-ui">{template.description}</p>
      {template.cases.length > 0 && (
        <ul aria-label="Cases" className="flex flex-col gap-0.5 text-muted-foreground text-xs">
          {template.cases.map((templateCase) => (
            <li key={templateCase.name}>{templateCase.name}</li>
          ))}
        </ul>
      )}
      {useTemplate.isError && (
        <p className="text-destructive text-xs">Couldn't create the workflow. Try again.</p>
      )}
      <Button
        variant="outline"
        size="sm"
        className="self-start"
        componentId="coral.desk.use_template"
        loading={useTemplate.isPending}
        onClick={() => useTemplate.mutate()}
      >
        Use template
      </Button>
    </div>
  );
}

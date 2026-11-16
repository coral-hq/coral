import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CheckIcon, XIcon } from "lucide-react";
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
import { useHosts } from "@/hooks/useHosts";
import { useNavigate } from "@/lib/routing";
import { cn } from "@/lib/utils";
import { WorkspacePickerDialog } from "@/shell/WorkspacePickerDialog";
import { runPreflight, startRun } from "../api/client";
import { runPath } from "../nav/coralPaths";

export interface StartRunDialogProps {
  workflowKey: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function StartRunDialog({ workflowKey, open, onOpenChange }: StartRunDialogProps) {
  const navigate = useNavigate();
  const hosts = useHosts({ enabled: open });
  const [hostId, setHostId] = useState<string | null>(null);
  const [workspacePath, setWorkspacePath] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  const onlineHosts = (hosts.data ?? []).filter((host) => host.status === "online");
  const request =
    hostId && workspacePath
      ? { workflow_key: workflowKey, host_id: hostId, workspace_path: workspacePath }
      : null;

  const preflight = useQuery({
    queryKey: ["coral-preflight", request],
    queryFn: () => runPreflight(request!),
    enabled: open && request !== null,
  });
  const start = useMutation({
    mutationFn: () => startRun(request!),
    onSuccess: ({ run_id }) => {
      onOpenChange(false);
      navigate(runPath(run_id));
    },
  });

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
                    onClick={() => {
                      setHostId(host.host_id);
                      setWorkspacePath(null);
                    }}
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
                {workspacePath ?? "None selected"}
              </code>
              <Button
                variant="outline"
                size="sm"
                disabled={!hostId}
                onClick={() => setPickerOpen(true)}
              >
                Choose folder
              </Button>
            </div>
          </section>

          {request && (
            <section className="flex flex-col gap-1" data-testid="preflight">
              <h3 className="font-medium text-foreground text-ui">Preflight</h3>
              {preflight.isPending ? (
                <Spinner className="size-4 text-muted-foreground" aria-label="Running preflight" />
              ) : preflight.isError ? (
                <p className="text-destructive text-ui">Preflight failed to run.</p>
              ) : (
                <ul>
                  {preflight.data.items.map((item) => (
                    <li
                      key={item.id}
                      data-ok={item.ok}
                      className={cn(
                        "flex items-center gap-2 text-ui",
                        item.ok ? "text-foreground" : "text-destructive",
                      )}
                    >
                      {item.ok ? <CheckIcon className="size-4" /> : <XIcon className="size-4" />}
                      <span>{item.label}</span>
                      {item.detail && (
                        <span className="text-muted-foreground text-xs">{item.detail}</span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </section>
          )}

          {start.isError && (
            <p className="text-destructive text-ui" role="alert">
              Couldn't start the run. Try again.
            </p>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button
              componentId="coral.start_run.submit"
              loading={start.isPending}
              disabled={!preflight.data?.ok}
              onClick={() => start.mutate()}
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
        onConfirm={setWorkspacePath}
        title="Select repository folder"
        description="Choose the repository the workflow will run in."
      />
    </>
  );
}

import { useQuery } from "@tanstack/react-query";
import { sessionQueryOptions } from "@/hooks/useSession";
import { Link } from "@/lib/routing";
import { isCoralAvailable, useCoralInfo } from "../gate/useCoralInfo";
import { runPath } from "../nav/coralPaths";
import { runIdOf, runRoleOf } from "./coralLabels";

/**
 * "Part of a run · Open run" in a run session's Chat header: the way back to the run from
 * its anchor, orchestrator or a step (a step opens on its own transcript). It reads only
 * the session snapshot AppShell already cached, and asks whether Coral is on only for a
 * run's session, so an ordinary session's header renders nothing and fetches nothing.
 */
export function CoralRunChip({ conversationId }: { conversationId: string }) {
  const { data: session } = useQuery({ ...sessionQueryOptions(conversationId), enabled: false });
  const labels = { labels: session?.labels ?? {} };
  const runId = runIdOf(labels);
  const { data: info } = useCoralInfo({ enabled: runId !== null });
  if (runId === null || !isCoralAvailable(info)) return null;
  const agent = runRoleOf(labels) === "step" ? conversationId : undefined;
  return (
    <span data-testid="coral-run-chip" className="shrink-0 text-xs text-muted-foreground">
      Part of a run ·{" "}
      <Link
        to={runPath(runId, { agent })}
        componentId="workflows.session.open_run"
        className="hover:text-foreground hover:underline"
      >
        Open run
      </Link>
    </span>
  );
}

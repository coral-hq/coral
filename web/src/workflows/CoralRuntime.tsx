import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import type { Conversation } from "@/hooks/useConversations";
import { useSidebarData } from "@/hooks/useSidebarData";
import { registerInboxKind } from "@/lib/inboxKinds";
import { isCoralAvailable, useCoralInfo } from "./gate/useCoralInfo";
import { useWorkflowInbox, WORKFLOW_INBOX_QUERY_KEY } from "./inbox/useWorkflowInbox";
import { useWorkflowInboxKind } from "./inbox/workflowInboxKind";
import { useWorkflowRunNotifications } from "./notifications/useWorkflowRunNotifications";
import { isRunAnchor } from "./session/coralLabels";

/** The run anchors' pending counts, as one comparable string. */
function anchorCounts(rows: readonly Conversation[]): string {
  return rows
    .filter(isRunAnchor)
    .map((row) => `${row.id}:${row.pending_elicitations_count ?? 0}`)
    .sort()
    .join(",");
}

/**
 * Coral's app-wide runtime, mounted once inside the session-updates provider:
 * the workflow Inbox kind and run notifications. Renders nothing. Without Coral
 * (no plugin, disabled, or info still loading) it registers nothing and loads no
 * feed, so gate prompts stay ordinary approvals that still answer.
 */
export function CoralRuntime(): null {
  const { identityReady, serverInboxRows, serverLoadedRows } = useSidebarData();
  const { data: info } = useCoralInfo({ enabled: identityReady });
  const enabled = identityReady && isCoralAvailable(info);
  const inbox = useWorkflowInbox(enabled);
  const kind = useWorkflowInboxKind(inbox, serverInboxRows, enabled);

  // Registering the same id again replaces the kind in place; only the latest
  // registration's unregister removes it, on disable or unmount.
  const unregister = useRef<(() => void) | null>(null);
  useEffect(() => {
    if (kind === null) {
      unregister.current?.();
      unregister.current = null;
      return;
    }
    unregister.current = registerInboxKind(kind);
  }, [kind]);
  useEffect(
    () => () => {
      unregister.current?.();
      unregister.current = null;
    },
    [],
  );

  // A gate opening, closing or being re-asked moves its anchor's count over the
  // session stream; reload the feed then instead of on the next minute.
  const queryClient = useQueryClient();
  const counts = anchorCounts(serverLoadedRows);
  const seenCounts = useRef(counts);
  useEffect(() => {
    if (counts === seenCounts.current) return;
    seenCounts.current = counts;
    if (enabled) void queryClient.invalidateQueries({ queryKey: WORKFLOW_INBOX_QUERY_KEY });
  }, [counts, enabled, queryClient]);

  useWorkflowRunNotifications(
    enabled,
    inbox.loaded ? inbox.alerts : undefined,
    serverLoadedRows,
    inbox.scope,
  );
  return null;
}

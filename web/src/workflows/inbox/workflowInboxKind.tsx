import { useMemo } from "react";
import type { Conversation } from "@/hooks/useConversations";
import { useViewerId } from "@/hooks/useViewerId";
import type { InboxKind } from "@/lib/inboxKinds";
import { runIdOf } from "../session/coralLabels";
import type { WorkflowInbox } from "./useWorkflowInbox";
import { WorkflowAlertCard, WorkflowGateCard } from "./WorkflowInboxCard";
import {
  badgeCount,
  isWorkflowGateEvent,
  workflowEntries,
  type WorkflowEntryData,
} from "./workflowEntries";

export const WORKFLOW_INBOX_KIND_ID = "workflow";
const FEED_ERROR = "Couldn’t load workflow alerts.";

const summary = (count: number) => (count === 1 ? "1 workflow item" : `${count} workflow items`);
const silences = (row: Conversation) => runIdOf(row) !== null;

/**
 * The workflow Inbox kind: one card per gate (claimed out of the approvals), one
 * per other alert. `null` while disabled. The same object is returned until
 * something it shows changes, since every new kind re-registers.
 *
 * :param rows: Session rows with the server's pending counts, for the badge.
 */
export function useWorkflowInboxKind(
  inbox: WorkflowInbox,
  rows: readonly Conversation[],
  enabled: boolean,
): InboxKind | null {
  const viewerId = useViewerId();
  const { alerts, incomplete, isLoading, isError, refetch, ack } = inbox;
  // The runtime re-renders on every sidebar update; count only when the inputs change.
  const badge = useMemo(() => badgeCount(alerts, rows), [alerts, rows]);
  return useMemo(() => {
    if (!enabled) return null;
    return {
      id: WORKFLOW_INBOX_KIND_ID,
      claims: isWorkflowGateEvent,
      entries: (claimed) => workflowEntries(alerts, claimed),
      badgeCount: badge,
      incomplete,
      loading: isLoading,
      error: isError ? { message: FEED_ERROR, retry: refetch } : null,
      summary,
      silences,
      render: (entry, expanded, onToggle, ui) => {
        const data = entry.data as WorkflowEntryData;
        return data.type === "gate" ? (
          <WorkflowGateCard
            data={data}
            at={entry.at}
            viewerId={viewerId}
            expanded={expanded}
            onToggle={onToggle}
            ui={ui}
          />
        ) : (
          <WorkflowAlertCard
            alert={data.alert}
            at={entry.at}
            expanded={expanded}
            onToggle={onToggle}
            ui={ui}
            onMarkRead={ack}
          />
        );
      },
    };
  }, [enabled, alerts, badge, incomplete, isLoading, isError, refetch, ack, viewerId]);
}

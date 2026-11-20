import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { useViewerId } from "@/hooks/useViewerId";
import { withBasePath } from "@/lib/basePath";
import { getOmnigentHostGeneration, getOmnigentServerIdentity } from "@/lib/host";
import { useRebasePath } from "@/lib/routing";
import type { WorkflowAlert } from "../api/types";
import { ackWorkflowAlert, fetchWorkflowInboxPage, WorkflowInboxError } from "./workflowInboxApi";

export const WORKFLOW_INBOX_QUERY_KEY = ["coral-inbox"] as const;
/** Pages read per load: up to 1,000 alerts, then the feed is incomplete. */
export const WORKFLOW_INBOX_MAX_PAGES = 10;

interface WorkflowFeed {
  alerts: WorkflowAlert[];
  incomplete: boolean;
  absent: boolean;
}

/** The caller's workflow alerts, as the Inbox, badge and notifier read them. */
export interface WorkflowInbox {
  alerts: readonly WorkflowAlert[];
  /** The feed has answered at least once (a server without one counts). */
  loaded: boolean;
  /** More alerts exist than were loaded. */
  incomplete: boolean;
  /** The server has no workflow Inbox (404): no alerts and no error. */
  absent: boolean;
  isLoading: boolean;
  isError: boolean;
  refetch: () => void;
  /** Mark an alert read: hidden until the server answers, back if it refuses. */
  ack: (alertId: string) => void;
  /** The viewer and server the feed belongs to. */
  scope: string;
}

const NO_ALERTS: readonly WorkflowAlert[] = Object.freeze([]);
const NO_IDS: ReadonlySet<string> = new Set();

/** Load the whole feed, following the cursor past empty pages, up to the page budget. */
async function loadWorkflowFeed(signal: AbortSignal): Promise<WorkflowFeed> {
  const alerts = new Map<string, WorkflowAlert>();
  let after: string | undefined;
  for (let page = 0; page < WORKFLOW_INBOX_MAX_PAGES; page += 1) {
    let result;
    try {
      // oxlint-disable-next-line no-await-in-loop -- each page's cursor comes from the one before.
      result = await fetchWorkflowInboxPage(after, signal);
    } catch (error) {
      if (page === 0 && error instanceof WorkflowInboxError && error.status === 404) {
        return { alerts: [], incomplete: false, absent: true };
      }
      throw error;
    }
    for (const alert of result.data) alerts.set(alert.alert_id, alert);
    if (result.next_cursor === null) {
      return { alerts: [...alerts.values()], incomplete: false, absent: false };
    }
    after = result.next_cursor;
  }
  return { alerts: [...alerts.values()], incomplete: true, absent: false };
}

/** No retry on 4xx; one retry on 5xx or network errors. */
function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof WorkflowInboxError && error.status < 500) return false;
  return failureCount < 1;
}

/**
 * The caller's open workflow alerts, the whole feed reloaded every minute while
 * `enabled`, also while the app is in the background (pause and run-end alerts
 * notify from it). One query loads every page in order, so each load is one
 * consistent list.
 */
export function useWorkflowInbox(enabled: boolean): WorkflowInbox {
  const queryClient = useQueryClient();
  const viewerId = useViewerId();
  const rebasePath = useRebasePath();
  const server = getOmnigentServerIdentity();
  const scope = JSON.stringify([
    server ?? `mount:${getOmnigentHostGeneration()}`,
    withBasePath(rebasePath("/")),
    viewerId,
  ]);
  const active = enabled && viewerId !== null;
  const queryKey = useMemo(() => [...WORKFLOW_INBOX_QUERY_KEY, scope], [scope]);
  const query = useQuery({
    queryKey,
    queryFn: ({ signal }) => loadWorkflowFeed(signal),
    enabled: active,
    staleTime: 30_000,
    refetchInterval: 60_000,
    refetchIntervalInBackground: true,
    retry: shouldRetry,
  });
  const { data, refetch: refetchQuery } = query;

  const refetch = useCallback(() => void refetchQuery(), [refetchQuery]);
  // Alerts being marked read stay hidden until the ack settles, whatever loads meanwhile.
  const [acking, setAcking] = useState(NO_IDS);
  const ack = useCallback(
    (alertId: string) => {
      setAcking((ids) => new Set(ids).add(alertId));
      const settle = () =>
        setAcking((ids) => {
          const next = new Set(ids);
          next.delete(alertId);
          return next.size === 0 ? NO_IDS : next;
        });
      const gone = () => {
        queryClient.setQueryData<WorkflowFeed>(
          queryKey,
          (feed) => feed && { ...feed, alerts: feed.alerts.filter((a) => a.alert_id !== alertId) },
        );
        void queryClient.invalidateQueries({ queryKey }).finally(settle);
      };
      ackWorkflowAlert(alertId).then(gone, (error: unknown) =>
        // 404: already read or resolved elsewhere, so it stays gone.
        error instanceof WorkflowInboxError && error.status === 404 ? gone() : settle(),
      );
    },
    [queryClient, queryKey],
  );

  const loadedAlerts = active ? (data?.alerts ?? NO_ALERTS) : NO_ALERTS;
  const alerts = useMemo(
    () =>
      acking.size === 0
        ? loadedAlerts
        : loadedAlerts.filter((alert) => !acking.has(alert.alert_id)),
    [loadedAlerts, acking],
  );
  return {
    alerts,
    loaded: active && data !== undefined,
    incomplete: active && data?.incomplete === true,
    absent: active && data?.absent === true,
    isLoading: active && query.isLoading,
    isError: active && query.isError,
    refetch,
    ack,
    scope,
  };
}

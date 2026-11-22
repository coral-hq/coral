import { useIsMutating, useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { RunDetail, SlotOut } from "../api/generated/coralApi";
import { retryStep, runQueryKey, runRetryKey } from "../api/runsApi";
import { CardStatusLine } from "../inbox/CardStatusLine";
import {
  refreshAfterRunAction,
  refreshAfterRunActionError,
  runActionErrorText,
} from "../inbox/RunActions";
import { useOnline } from "../inbox/useOnline";
import { isolated, nodeLabel, type GraphNodeNames } from "../shared/pauseCopy";
import { useCoralScope } from "../shared/viewerScope";
import { runViewCardUi } from "./gateCardUi";

// A paused run's Retry buttons: one per failed step the run's detail says a retry may
// restart now. Each button sends one request at a time. The status line above them stays
// mounted with the banner and says how the latest request went, even after its button is
// gone; a new offer or the end of a restart clears it.

/** What a retry the server took tells the owner. */
export const RETRYING_TEXT = "Retrying.";

export interface RetryStepButtonsProps {
  runId: string;
  /** The detail's `retry_activation_ids`: store activation ids, in cause order. */
  activationIds: readonly string[];
  /** The detail's slots, whose `activation_id` and `node_id` name each step. */
  slots: readonly Pick<SlotOut, "activation_id" | "node_id">[];
  /** The run's graph, for step names; `null` until it loads. */
  graph: GraphNodeNames | null;
  /** A step of the run is restarting (an `infra` / `recovery.restarting` cause). */
  restarting: boolean;
}

interface Outcome {
  text: string;
  failed: boolean;
}

/** "Retry <step>" with the step's name isolated, or "Retry a step" when it cannot be named. */
export function retryLabel(
  activationId: string,
  slots: RetryStepButtonsProps["slots"],
  graph: GraphNodeNames | null,
): string {
  const nodeId = slots.find((slot) => slot.activation_id === activationId)?.node_id;
  const name = nodeId === undefined ? null : nodeLabel(graph, nodeId);
  return `Retry ${name === null ? "a step" : isolated(name)}`;
}

export function RetryStepButtons({
  runId,
  activationIds,
  slots,
  graph,
  restarting,
}: RetryStepButtonsProps) {
  const statusRef = useRef<HTMLParagraphElement>(null);
  const [outcome, setOutcome] = useState<Outcome | null>(null);
  const offered = activationIds.length > 0;
  // The last result is over once a step is offered again after none (a restart that
  // failed) or a restart ends.
  const [seen, setSeen] = useState({ offered, restarting });
  if (offered !== seen.offered || restarting !== seen.restarting) {
    setSeen({ offered, restarting });
    if ((offered && !seen.offered) || (seen.restarting && !restarting)) setOutcome(null);
  }

  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (outcome === null) return;
    // A late result never pulls focus from elsewhere on the page.
    const focused = document.activeElement;
    if (
      focused === null ||
      focused === document.body ||
      containerRef.current?.contains(focused) === true
    ) {
      statusRef.current?.focus();
    }
  }, [outcome]);

  return (
    <div
      ref={containerRef}
      data-testid="run-retry-steps"
      className={cn("flex flex-col gap-1", (offered || outcome !== null) && "pt-1")}
    >
      <CardStatusLine
        ref={statusRef}
        message={outcome?.text ?? null}
        failed={outcome?.failed === true}
      />
      {offered && (
        <runViewCardUi.InboxActions>
          {[...new Set(activationIds)].map((activationId) => (
            <RetryStepButton
              key={activationId}
              runId={runId}
              activationId={activationId}
              label={retryLabel(activationId, slots, graph)}
              onOutcome={setOutcome}
            />
          ))}
        </runViewCardUi.InboxActions>
      )}
    </div>
  );
}

interface RetryStepButtonProps {
  runId: string;
  activationId: string;
  label: string;
  /**
   * The banner's result setter. Cleared when a request starts, so the same text again is
   * announced again; set when it settles, even if this button is gone by then.
   */
  onOutcome: (outcome: Outcome | null) => void;
}

function RetryStepButton({ runId, activationId, label, onOutcome }: RetryStepButtonProps) {
  const queryClient = useQueryClient();
  const { scope, ready: viewerKnown } = useCoralScope();
  const online = useOnline();
  const retryKey = runRetryKey(scope, runId, activationId);
  // Set at the click, so a second click finds the button disabled.
  const [pending, setPending] = useState(false);
  // The server took the retry; the button goes once the detail stops offering the step.
  const [taken, setTaken] = useState(false);
  const retry = useMutation({
    mutationKey: retryKey,
    mutationFn: () => retryStep(runId, activationId),
    // Sent at once, as a plain request: never held back until React Query sees the network.
    networkMode: "always",
    // These run even if this button unmounted meanwhile, so the run refreshes and the
    // banner still says how the retry went.
    onSuccess: (summary) => {
      // Taken, so the cached detail stops offering the step before its re-read lands; edited
      // before the refresh, so the refresh still marks it stale.
      queryClient.setQueryData<RunDetail>(runQueryKey(scope, runId), (detail) =>
        detail
          ? {
              ...detail,
              retry_activation_ids: detail.retry_activation_ids.filter((id) => id !== activationId),
            }
          : detail,
      );
      refreshAfterRunAction(queryClient, scope, runId, summary);
      onOutcome({ text: RETRYING_TEXT, failed: false });
    },
    onError: (error) => {
      refreshAfterRunActionError(queryClient, scope, runId, error);
      onOutcome({ text: runActionErrorText(error), failed: true });
    },
  });
  // A request sent before the banner was last shown is still this step's.
  const inFlight = useIsMutating({ mutationKey: retryKey }) > 0;
  const ready = online && viewerKnown && !pending && !inFlight && !taken;

  const send = () => {
    if (!ready) return;
    setPending(true);
    onOutcome(null);
    retry.mutate(undefined, {
      onSuccess: () => setTaken(true),
      onSettled: () => setPending(false),
    });
  };

  return (
    <Button
      size="xs"
      className={runViewCardUi.primaryAction}
      loading={pending || inFlight}
      disabled={!ready}
      onClick={send}
      componentId="workflows.run.retry_step"
    >
      {label}
    </Button>
  );
}

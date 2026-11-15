import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { isCoralAvailable, isCoralMissingError, useCoralInfo } from "./useCoralInfo";

/**
 * Gate for Coral desk routes. Loading never reads as "not found"; a missing
 * plugin, `enabled: false` or an off sub-feature does; an outage offers Retry.
 */
export function CoralGate({ subFeature, children }: { subFeature?: string; children: ReactNode }) {
  const { data, error, isPending, refetch } = useCoralInfo();

  // Cached info wins over a failed background refetch.
  if (data) return isCoralAvailable(data, subFeature) ? children : <NotFoundPage />;
  if (isPending) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center">
        <Spinner className="size-5 text-muted-foreground" aria-label="Loading" />
      </div>
    );
  }
  if (!isCoralMissingError(error)) {
    return (
      <div className="flex flex-1 items-center justify-center px-6" data-testid="coral-gate-error">
        <div className="flex max-w-sm flex-col items-center gap-3 text-center">
          <h1 className="font-medium text-foreground text-lg">Couldn't load Coral</h1>
          <p className="text-muted-foreground text-ui">Check your connection and try again.</p>
          <Button variant="outline" componentId="coral.gate.retry" onClick={() => void refetch()}>
            Retry
          </Button>
        </div>
      </div>
    );
  }
  return <NotFoundPage />;
}

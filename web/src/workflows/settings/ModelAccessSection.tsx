import { Link } from "@/lib/routing";
import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { Button } from "@/components/ui/button";
import { useCoralInfo } from "../gate/useCoralInfo";
import { subscriptionOptionVisible } from "./authBadge";

/**
 * Coral Model access settings (HRN-04). API key is the recommended path;
 * subscription stays dark while OQ-28 is unresolved.
 */
export function ModelAccessSection() {
  const { data } = useCoralInfo();
  const nativeSteps = Boolean(data?.sub_features?.claude_native_steps);
  const showSubscription = subscriptionOptionVisible(nativeSteps);

  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid="model-access-section"
    >
      <CoralPageHeader
        title="Model access"
        description="Choose how Coral steps reach Claude. API keys are recommended for workflows."
      />
      <div className="flex flex-col gap-6 py-8 md:flex-row md:items-stretch">
        <section
          className="flex flex-1 flex-col gap-3 rounded-lg border border-border p-4"
          data-testid="model-access-api-key"
        >
          <h2 className="text-ui font-medium">API key (recommended for workflows)</h2>
          <p className="text-muted-foreground text-ui">
            Opens the host credential form used by Claude harnesses. Steps run on claude-sdk with
            fail-closed policy hooks.
          </p>
          <Button asChild className="mt-auto w-full sm:w-auto">
            <Link to="/settings/harnesses">Open harness credentials</Link>
          </Button>
        </section>
        {showSubscription ? (
          <section
            className="flex flex-1 flex-col gap-3 rounded-lg border border-border p-4"
            data-testid="model-access-subscription"
          >
            <h2 className="text-ui font-medium">Claude subscription</h2>
            <p className="text-muted-foreground text-ui">
              Steps run on claude-native. Some guarantees are weaker than the API-key path.
            </p>
          </section>
        ) : null}
      </div>
    </PageScroll>
  );
}

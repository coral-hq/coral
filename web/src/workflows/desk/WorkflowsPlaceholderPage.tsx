import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";
import { CORAL_LABELS } from "../nav/labels";

/** Empty Workflows desk until the real library lands. */
export function WorkflowsPlaceholderPage() {
  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid="workflows-placeholder"
    >
      <CoralPageHeader
        title={CORAL_LABELS.workflows}
        description="Multi-agent workflows you can run and inspect."
      />
      <div className="flex flex-col items-center gap-2 py-16 text-center">
        <h2 className="font-medium text-foreground text-lg">No workflows yet</h2>
        <p className="max-w-sm text-muted-foreground text-ui">
          Upload a workflow through the API or CLI and it will appear here.
        </p>
      </div>
    </PageScroll>
  );
}

import type { ReactNode } from "react";
import { PageScroll } from "@/components/PageScroll";
import { CoralPageHeader } from "@/brand/CoralPageHeader";

/** Stand-in for desks owned by later work (run view, editor, settings, profiles). */
export function DeskPlaceholderPage({
  title,
  detail,
  testId,
}: {
  title: string;
  detail?: ReactNode;
  testId: string;
}) {
  return (
    <PageScroll
      maxWidthClassName="max-w-[960px]"
      contentClassName="px-4 md:px-10"
      data-testid={testId}
    >
      <CoralPageHeader title={title} description={detail} />
      <p className="py-16 text-center text-muted-foreground text-ui">Coming soon.</p>
    </PageScroll>
  );
}

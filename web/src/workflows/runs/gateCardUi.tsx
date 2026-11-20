import { useId, type ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import type { InboxCardProps, InboxKindUi, InboxTileTone } from "@/lib/inboxKinds";
import { cn } from "@/lib/utils";

// The card primitives the Inbox's workflow cards render with, for the run page: a card is
// always open (it is what the page asks the owner to act on), and has no toggle or time.

const TILE_TONES: Readonly<Record<InboxTileTone, string>> = {
  yellow: "bg-status-yellow/12 text-status-yellow",
  gray: "bg-status-gray/12 text-status-gray",
  red: "bg-status-red/12 text-status-red",
};

function RunViewCard({ testId, dataKind, tile, kindLabel, preview, children }: InboxCardProps) {
  const headingId = useId();
  return (
    <section
      data-testid={testId}
      data-kind={dataKind}
      aria-labelledby={headingId}
      className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4"
    >
      <div className="flex min-w-0 items-center gap-3">
        {tile}
        <h2 id={headingId} className="min-w-0 truncate text-ui font-medium text-foreground">
          {kindLabel}
          {preview ? <span className="font-normal text-muted-foreground">: {preview}</span> : null}
        </h2>
      </div>
      {children}
    </section>
  );
}

function RunViewTile({ icon: Icon, tone }: { icon: LucideIcon; tone: InboxTileTone }) {
  return (
    <span
      data-testid="run-card-tile"
      data-tone={tone}
      className={cn(
        "flex size-8 shrink-0 items-center justify-center rounded-lg",
        TILE_TONES[tone],
      )}
    >
      <Icon aria-hidden className="size-4" />
    </span>
  );
}

function RunViewActions({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2">{children}</div>;
}

/** The run page's `InboxKindUi`: cards always open, compact actions. */
export const runViewCardUi: InboxKindUi = {
  InboxCard: RunViewCard,
  KindTile: RunViewTile,
  InboxActions: RunViewActions,
  outlineAction:
    "rounded-md border-button-border bg-transparent text-muted-foreground hover:text-foreground",
  primaryAction: "rounded-md bg-foreground text-card hover:bg-foreground/80 [&_svg]:text-card",
};

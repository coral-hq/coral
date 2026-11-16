import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { AccentRail } from "./AccentRail";

export interface CoralPageHeaderProps {
  title: string;
  description?: ReactNode;
  /** Right-hand actions; they wrap below the title at phone width. */
  actions?: ReactNode;
  /** Rendered inline after the title (counts, info buttons). */
  titleAccessory?: ReactNode;
  /**
   * `list` sits inside a `PageScroll` column. `fullBleed` is for pages that own
   * their own scroll area and clear the shell's sidebar toggle.
   */
  variant?: "list" | "fullBleed";
  className?: string;
}

/** Shared desk header: accent rail, Newsreader title, description, actions. */
export function CoralPageHeader({
  title,
  description,
  actions,
  titleAccessory,
  variant = "list",
  className,
}: CoralPageHeaderProps) {
  return (
    <header
      data-variant={variant}
      className={cn(
        "flex flex-wrap items-start justify-between gap-x-4 gap-y-3",
        variant === "list" ? "mb-6" : "canvas-page-heading px-6 pt-2 max-md:pt-3 max-md:pl-16",
        className,
      )}
    >
      <div className="flex min-w-0 items-stretch gap-3">
        <AccentRail />
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="font-display text-[24px] leading-tight font-medium tracking-[-0.02em] text-foreground">
              {title}
            </h1>
            {titleAccessory}
          </div>
          {description ? <p className="text-ui text-muted-foreground">{description}</p> : null}
        </div>
      </div>
      {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

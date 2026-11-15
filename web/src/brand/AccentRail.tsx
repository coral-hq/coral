import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";

/** Decorative vertical rail in the brand accent beside a desk title. */
export function AccentRail({ className, ...props }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span
      aria-hidden="true"
      data-testid="accent-rail"
      className={cn("w-1 shrink-0 self-stretch rounded-full bg-brand-accent", className)}
      {...props}
    />
  );
}

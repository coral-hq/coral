import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import { CoralMark } from "./CoralMark";

/**
 * The Coral wordmark: the mark beside "Coral" in the Newsreader display face,
 * sharing one optically centred row (UI§3.3, §4.2).
 */
export function CoralWordmark({
  name = "Coral",
  className,
  ...props
}: { name?: string } & HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className={cn("inline-flex items-center gap-2.5 leading-none", className)} {...props}>
      <CoralMark className="block size-7 shrink-0" />
      <span className="font-display text-[20px] leading-none font-medium tracking-[-0.03em] text-foreground">
        {name}
      </span>
    </span>
  );
}

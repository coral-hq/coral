import { forwardRef } from "react";
import { cn } from "@/lib/utils";

export interface CardStatusLineProps {
  /** The card's latest result or refusal; `null` while there is none. */
  message: string | null;
  /** The message reports a failure. */
  failed?: boolean;
  /** A passing condition said after the message, such as being offline. */
  notice?: string | null;
}

/**
 * A card's status line: a polite live region that a result moves focus to. The
 * notice has its own node, so it comes and goes without the message being
 * announced again.
 */
export const CardStatusLine = forwardRef<HTMLParagraphElement, CardStatusLineProps>(
  function CardStatusLine({ message, failed = false, notice = null }, ref) {
    return (
      <p
        ref={ref}
        tabIndex={-1}
        role="status"
        aria-live="polite"
        // Kept in the accessibility tree while empty, so its first message is announced.
        className={cn(
          "text-sm text-muted-foreground outline-none",
          message === null && notice === null && "sr-only",
        )}
      >
        {message !== null && <span className={cn(failed && "text-destructive")}>{message}</span>}
        {message !== null && notice !== null && " "}
        {notice !== null && <span>{notice}</span>}
      </p>
    );
  },
);

import { createPortal } from "react-dom";
import { Spinner } from "@/components/ui/spinner";
import { getEmbedRoot } from "@/lib/host";

// The drawer's panel, and what shows in it while the drawer's code loads. Kept apart from
// the drawer so the run page can show it without loading the transcript's modules.

export const DRAWER_PANEL_CLASS =
  "fixed inset-y-0 right-0 z-40 flex w-full flex-col border-border bg-background shadow-lg md:w-[480px] md:border-l";

/** Where the drawer renders: the embed's root inside a host page, else the document. */
export function drawerRoot(): HTMLElement {
  return getEmbedRoot() ?? document.body;
}

export function StepDrawerFallback() {
  return createPortal(
    <div data-testid="step-drawer-loading" className={DRAWER_PANEL_CLASS}>
      <p role="status" className="m-auto flex items-center gap-2 text-sm text-muted-foreground">
        <Spinner aria-hidden className="size-4" />
        Loading the step’s transcript…
      </p>
    </div>,
    drawerRoot(),
  );
}

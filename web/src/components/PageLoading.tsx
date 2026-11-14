import { Spinner } from "@/components/ui/spinner";
import { useAppName } from "@/lib/branding";

// CORAL(S89): the default label names the app via useAppName() (Coral by default), not "Omnigent".
export function PageLoading({ label }: { label?: string }) {
  const appName = useAppName();
  return (
    <div
      className="flex min-h-screen items-center justify-center gap-3 bg-background text-muted-foreground"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <Spinner className="size-5 motion-reduce:animate-none" aria-hidden="true" />
      <span>{label ?? `Loading ${appName}…`}</span>
    </div>
  );
}

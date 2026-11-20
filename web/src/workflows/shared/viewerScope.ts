import { useMemo } from "react";
import { useViewerId } from "@/hooks/useViewerId";
import { withBasePath } from "@/lib/basePath";
import { getOmnigentHostGeneration, getOmnigentServerIdentity } from "@/lib/host";
import { useRebasePath } from "@/lib/routing";

// The viewer and server every Coral query belongs to, so a cached feed or run is never
// shown to another viewer or read back from another server.

/** The scope of Coral's cached queries; `ready` once the viewer is known. */
export interface CoralScope {
  scope: string;
  /** Queries stay disabled until the viewer is known (`"local"` on a single-user server). */
  ready: boolean;
}

/**
 * The scope string of `viewerId` on this server at `appRoot`: the server's identity (an
 * embedded host's mount when it names none), the app root and the viewer.
 */
export function coralScope(viewerId: string | null, appRoot: string): string {
  const server = getOmnigentServerIdentity() ?? `mount:${getOmnigentHostGeneration()}`;
  return JSON.stringify([server, appRoot, viewerId]);
}

/** The current viewer's Coral scope, the one object until the viewer or server changes. */
export function useCoralScope(): CoralScope {
  const viewerId = useViewerId();
  const rebasePath = useRebasePath();
  const scope = coralScope(viewerId, withBasePath(rebasePath("/")));
  const ready = viewerId !== null;
  return useMemo(() => ({ scope, ready }), [scope, ready]);
}

import { useQuery } from "@tanstack/react-query";
import { authenticatedFetch } from "@/lib/identity";
import type { CoralInfo } from "../api/types";

export const CORAL_INFO_QUERY_KEY = ["coral-info"] as const;
const CORAL_INFO_STALE_TIME_MS = 5 * 60 * 1000;

export class CoralInfoError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.name = "CoralInfoError";
    this.status = status;
  }
}

function isCoralInfo(value: unknown): value is CoralInfo {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<CoralInfo>;
  return (
    typeof candidate.enabled === "boolean" &&
    typeof candidate.sub_features === "object" &&
    candidate.sub_features !== null
  );
}

export async function fetchCoralInfo(signal?: AbortSignal): Promise<CoralInfo> {
  const response = await authenticatedFetch("/v1/coral/info", { signal });
  if (!response.ok) {
    throw new CoralInfoError(`Failed to load Coral info (${response.status})`, response.status);
  }
  const payload: unknown = await response.json();
  if (!isCoralInfo(payload)) throw new CoralInfoError("Invalid Coral info response");
  return payload;
}

/** The server has no Coral plugin: a definitive "not here", not an outage. */
export function isCoralMissingError(error: unknown): boolean {
  return error instanceof CoralInfoError && error.status === 404;
}

/** No retry on 4xx (404 means Coral is absent); one retry on 5xx or network errors. */
export function shouldRetryCoralInfo(failureCount: number, error: unknown): boolean {
  if (error instanceof CoralInfoError && error.status !== undefined && error.status < 500) {
    return false;
  }
  return failureCount < 1;
}

/** Whether Coral (and, when given, one sub-feature) is on for this server. */
export function isCoralAvailable(info: CoralInfo | undefined, subFeature?: string): boolean {
  if (!info?.enabled) return false;
  return subFeature === undefined || info.sub_features[subFeature] === true;
}

export function useCoralInfo() {
  return useQuery<CoralInfo, Error>({
    queryKey: CORAL_INFO_QUERY_KEY,
    queryFn: ({ signal }) => fetchCoralInfo(signal),
    staleTime: CORAL_INFO_STALE_TIME_MS,
    retry: shouldRetryCoralInfo,
  });
}

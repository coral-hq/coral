/** Pure badge copy for how a Coral step reaches Claude (HRN-04). */

export type AuthBadgeKind = "needs_api_key" | "api_key" | "subscription";

export interface AuthBadgeInput {
  /** Step harness id, e.g. ``claude-sdk`` or ``claude-native``. */
  harness: string | null;
  /** Host account credential reference when one is pinned. */
  credentialRef: string | null;
  /** Host account kind when known: ``api_key`` | ``subscription`` | null. */
  accountKind: "api_key" | "subscription" | null;
}

/** Badge label for a profile / step's Claude access path. */
export function authBadge(input: AuthBadgeInput): string {
  if (input.harness === "claude-native" && input.accountKind === "subscription") {
    return "Uses subscription (claude-native)";
  }
  if (input.credentialRef || input.accountKind === "api_key") {
    return "API key";
  }
  return "Needs API key";
}

/** Whether the subscription Model-access option may be shown (flag + OQ-28). */
export function subscriptionOptionVisible(claudeNativeSteps: boolean): boolean {
  // OQ-28 unresolved: keep subscription dark even when the flag is on.
  void claudeNativeSteps;
  return false;
}

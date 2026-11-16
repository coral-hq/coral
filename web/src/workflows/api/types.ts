/** `GET /v1/coral/info` response (FND-02). */
export interface CoralInfo {
  enabled: boolean;
  version: string;
  sub_features: Record<string, boolean>;
}

/** Sub-feature keys the web shell gates on. */
export const CORAL_SUB_FEATURE = {
  profilesDesk: "profiles_desk",
} as const;

import { describe, expect, it } from "vitest";
import { authBadge, subscriptionOptionVisible } from "./authBadge";

describe("authBadge", () => {
  it("names a missing key", () => {
    expect(authBadge({ harness: "claude-sdk", credentialRef: null, accountKind: null })).toBe(
      "Needs API key",
    );
  });

  it("names an API key path", () => {
    expect(
      authBadge({
        harness: "claude-sdk",
        credentialRef: "cred_1",
        accountKind: "api_key",
      }),
    ).toBe("API key");
  });

  it("names a subscription native path", () => {
    expect(
      authBadge({
        harness: "claude-native",
        credentialRef: null,
        accountKind: "subscription",
      }),
    ).toBe("Uses subscription (claude-native)");
  });
});

describe("subscriptionOptionVisible", () => {
  it("stays dark while OQ-28 is unresolved", () => {
    expect(subscriptionOptionVisible(false)).toBe(false);
    expect(subscriptionOptionVisible(true)).toBe(false);
  });
});

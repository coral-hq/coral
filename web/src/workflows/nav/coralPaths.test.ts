import { describe, expect, it } from "vitest";
import {
  isCoralDeskPath,
  isProfilesPathname,
  isWorkflowsPathname,
  profilesPath,
  runPath,
  workflowPath,
  workflowsPath,
} from "./coralPaths";

describe("coralPaths", () => {
  it("builds extensionless desk paths", () => {
    expect(workflowsPath()).toBe("/workflows");
    expect(profilesPath()).toBe("/profiles");
    expect(workflowPath("daily report")).toBe("/workflows/daily%20report");
  });

  it("builds run paths with optional focus params", () => {
    expect(runPath("r1")).toBe("/workflows/runs/r1");
    expect(runPath("r/1", { agent: "s1", node: "n2", scope: "loop", panel: "logs" })).toBe(
      "/workflows/runs/r%2F1?agent=s1&node=n2&scope=loop&panel=logs",
    );
    expect(runPath("r1", { agent: "s1", node: "" })).toBe("/workflows/runs/r1?agent=s1");
  });

  it("matches desk paths on a segment boundary", () => {
    for (const pathname of [
      "/workflows",
      "/workflows/",
      "/workflows/runs/r1",
      "/workflows/settings/gates",
      "/profiles",
    ]) {
      expect(isCoralDeskPath(pathname)).toBe(true);
    }
    for (const pathname of ["/", "/workflowsx", "/profiles-old", "/c/workflows", "/inbox"]) {
      expect(isCoralDeskPath(pathname)).toBe(false);
    }
    expect(isWorkflowsPathname("/profiles")).toBe(false);
    expect(isProfilesPathname("/workflows")).toBe(false);
  });

  it("honors an embedded mount path", () => {
    const rebase = (path: string) => `/mount${path}`;
    expect(isCoralDeskPath("/mount/workflows/runs/r1", rebase)).toBe(true);
    expect(isCoralDeskPath("/mount/profiles", rebase)).toBe(true);
    expect(isCoralDeskPath("/workflows", rebase)).toBe(false);
    expect(isCoralDeskPath("/mount", rebase)).toBe(false);
  });
});

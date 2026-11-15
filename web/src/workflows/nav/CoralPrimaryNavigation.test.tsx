import { cleanup, fireEvent, render, renderHook, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CoralInfo } from "../api/types";
import type * as CoralInfoModule from "../gate/useCoralInfo";

const state = vi.hoisted(() => ({ data: undefined as CoralInfo | undefined }));
vi.mock("../gate/useCoralInfo", async (importOriginal) => ({
  ...(await importOriginal<typeof CoralInfoModule>()),
  useCoralInfo: () => ({ data: state.data }),
}));

import { CoralPrimaryNavigation } from "./CoralPrimaryNavigation";
import { useCoralPaletteActions } from "./useCoralPaletteActions";

afterEach(() => {
  cleanup();
  state.data = undefined;
});

function renderNav(
  active = { workflowsActive: false, profilesActive: false },
  onNavigate = vi.fn(),
) {
  render(
    <MemoryRouter>
      <CoralPrimaryNavigation {...active} onNavigate={onNavigate} />
    </MemoryRouter>,
  );
  return onNavigate;
}

describe("CoralPrimaryNavigation", () => {
  it.each([
    ["info still loading", undefined],
    ["Coral disabled", { enabled: false, version: "1", sub_features: { profiles_desk: true } }],
  ])("renders nothing while %s", (_name, info) => {
    state.data = info;
    renderNav();

    expect(screen.queryByRole("link")).toBeNull();
  });

  it("renders only Workflows without profiles_desk, and marks it active", () => {
    state.data = { enabled: true, version: "1", sub_features: {} };
    const onNavigate = renderNav({ workflowsActive: true, profilesActive: false });

    const link = screen.getByRole("link", { name: "Workflows" });
    expect(link).toHaveAttribute("href", "/workflows");
    expect(link).toHaveAttribute("aria-current", "page");
    expect(screen.queryByRole("link", { name: "Agent Profiles" })).toBeNull();

    fireEvent.click(link);
    expect(onNavigate).toHaveBeenCalledOnce();
  });

  it("adds Agent Profiles after Workflows with profiles_desk", () => {
    state.data = { enabled: true, version: "1", sub_features: { profiles_desk: true } };
    renderNav({ workflowsActive: false, profilesActive: true });

    const links = screen.getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual(["Workflows", "Agent Profiles"]);
    expect(links[1]).toHaveAttribute("href", "/profiles");
    expect(links[1]).toHaveAttribute("aria-current", "page");
  });
});

describe("useCoralPaletteActions", () => {
  it("is empty until Coral is enabled", () => {
    const { result } = renderHook(() => useCoralPaletteActions(vi.fn()));
    expect(result.current).toEqual([]);
  });

  it("offers Go to Workflows, plus Profiles only with profiles_desk", () => {
    const navigate = vi.fn();
    state.data = { enabled: true, version: "1", sub_features: {} };
    const { result, rerender } = renderHook(() => useCoralPaletteActions(navigate));
    expect(result.current.map((action) => action.label)).toEqual(["Go to Workflows"]);

    result.current[0].run();
    expect(navigate).toHaveBeenCalledWith("/workflows");

    state.data = { enabled: true, version: "1", sub_features: { profiles_desk: true } };
    rerender();
    expect(result.current.map((action) => action.label)).toEqual([
      "Go to Workflows",
      "Go to Agent Profiles",
    ]);
    result.current[1].run();
    expect(navigate).toHaveBeenLastCalledWith("/profiles");
  });
});

import { lazy, type ComponentType } from "react";
import { Route } from "react-router-dom";
import { CORAL_SUB_FEATURE } from "./api/types";
import { CoralGate } from "./gate/CoralGate";

type WithPageView = <P extends object>(id: string, Component: ComponentType<P>) => ComponentType<P>;

const WorkflowsPage = lazy(() =>
  import("./desk/WorkflowsPlaceholderPage").then((m) => ({ default: m.WorkflowsPlaceholderPage })),
);
const RunPage = lazy(() =>
  import("./desk/WorkflowRunPlaceholderPage").then((m) => ({
    default: m.WorkflowRunPlaceholderPage,
  })),
);
const EditorPage = lazy(() =>
  import("./desk/WorkflowRunPlaceholderPage").then((m) => ({
    default: m.WorkflowEditorPlaceholderPage,
  })),
);
const SettingsPage = lazy(() =>
  import("./desk/WorkflowRunPlaceholderPage").then((m) => ({
    default: m.WorkflowSettingsPlaceholderPage,
  })),
);
const ProfilesPage = lazy(() =>
  import("./desk/ProfilesPlaceholderPage").then((m) => ({ default: m.ProfilesPlaceholderPage })),
);

interface DeskPages {
  Workflows: ComponentType;
  Run: ComponentType;
  Editor: ComponentType;
  Settings: ComponentType;
  Profiles: ComponentType;
}

// Wrapped components must keep a stable identity across renders, or every
// route-table render would remount the page.
const pagesByWrapper = new WeakMap<WithPageView, DeskPages>();

function deskPages(withPageView: WithPageView): DeskPages {
  let pages = pagesByWrapper.get(withPageView);
  if (!pages) {
    pages = {
      Workflows: withPageView("workflows", WorkflowsPage),
      Run: withPageView("workflows.run", RunPage),
      Editor: withPageView("workflows.editor", EditorPage),
      Settings: withPageView("workflows.settings", SettingsPage),
      Profiles: withPageView("profiles", ProfilesPage),
    };
    pagesByWrapper.set(withPageView, pages);
  }
  return pages;
}

/**
 * Coral desk routes, as a Fragment to drop inside the AppShell route group
 * before the catch-all. Every route is gated; `/profiles` also needs
 * `profiles_desk`.
 */
export function coralRoutes(prefix: string, withPageView: WithPageView) {
  const { Workflows, Run, Editor, Settings, Profiles } = deskPages(withPageView);
  return (
    <>
      <Route
        path={`${prefix}/workflows`}
        element={
          <CoralGate>
            <Workflows />
          </CoralGate>
        }
      />
      <Route
        path={`${prefix}/workflows/runs/:runId`}
        element={
          <CoralGate>
            <Run />
          </CoralGate>
        }
      />
      <Route
        path={`${prefix}/workflows/settings/*`}
        element={
          <CoralGate>
            <Settings />
          </CoralGate>
        }
      />
      <Route
        path={`${prefix}/workflows/:workflowKey`}
        element={
          <CoralGate>
            <Editor />
          </CoralGate>
        }
      />
      <Route
        path={`${prefix}/profiles`}
        element={
          <CoralGate subFeature={CORAL_SUB_FEATURE.profilesDesk}>
            <Profiles />
          </CoralGate>
        }
      />
    </>
  );
}

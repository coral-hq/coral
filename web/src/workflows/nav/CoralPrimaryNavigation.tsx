import { UserRoundIcon, WorkflowIcon } from "lucide-react";
import type { MouseEvent } from "react";
import { PrimaryNavLink } from "@/shell/PrimaryNavLink";
import { CORAL_SUB_FEATURE } from "../api/types";
import { isCoralAvailable, useCoralInfo } from "../gate/useCoralInfo";
import { profilesPath, workflowsPath } from "./coralPaths";
import { CORAL_LABELS } from "./labels";

/** Sidebar rows for the Coral desks; nothing renders until Coral is confirmed on. */
export function CoralPrimaryNavigation({
  workflowsActive,
  profilesActive,
  onNavigate,
}: {
  workflowsActive: boolean;
  profilesActive: boolean;
  onNavigate?: (event: MouseEvent<HTMLAnchorElement>) => void;
}) {
  const { data } = useCoralInfo();
  if (!isCoralAvailable(data)) return null;

  return (
    <>
      <PrimaryNavLink
        to={workflowsPath()}
        label={CORAL_LABELS.workflows}
        icon={WorkflowIcon}
        active={workflowsActive}
        onClick={onNavigate}
        componentId="sidebar.workflows"
        testId="workflows-nav"
      />
      {isCoralAvailable(data, CORAL_SUB_FEATURE.profilesDesk) && (
        <PrimaryNavLink
          to={profilesPath()}
          label={CORAL_LABELS.profiles}
          icon={UserRoundIcon}
          active={profilesActive}
          onClick={onNavigate}
          componentId="sidebar.profiles"
          testId="profiles-nav"
        />
      )}
    </>
  );
}

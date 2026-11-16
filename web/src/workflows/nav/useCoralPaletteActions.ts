import { useMemo } from "react";
import { UserRoundIcon, WorkflowIcon, type LucideIcon } from "lucide-react";
import { CORAL_SUB_FEATURE } from "../api/types";
import { isCoralAvailable, useCoralInfo } from "../gate/useCoralInfo";
import { profilesPath, workflowsPath } from "./coralPaths";
import { CORAL_LABELS } from "./labels";

export interface CoralPaletteAction {
  id: string;
  label: string;
  icon: LucideIcon;
  keywords: string[];
  run: () => void;
}

/** "Go to" palette actions for the Coral desks; empty while Coral is off or unknown. */
export function useCoralPaletteActions(navigate: (to: string) => void): CoralPaletteAction[] {
  const { data } = useCoralInfo();
  const enabled = isCoralAvailable(data);
  const profilesEnabled = isCoralAvailable(data, CORAL_SUB_FEATURE.profilesDesk);

  return useMemo(() => {
    if (!enabled) return [];
    const actions: CoralPaletteAction[] = [
      {
        id: "go-workflows",
        label: CORAL_LABELS.goToWorkflows,
        icon: WorkflowIcon,
        keywords: ["workflow", "runs", "coral"],
        run: () => navigate(workflowsPath()),
      },
    ];
    if (profilesEnabled) {
      actions.push({
        id: "go-profiles",
        label: CORAL_LABELS.goToProfiles,
        icon: UserRoundIcon,
        keywords: ["agent", "profile", "coral"],
        run: () => navigate(profilesPath()),
      });
    }
    return actions;
  }, [enabled, profilesEnabled, navigate]);
}

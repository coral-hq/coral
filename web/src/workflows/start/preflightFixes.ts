import type { PreflightFix } from "../api/generated/coralApi";

/** Human label for a preflight fix target. */
export function fixLabel(target: PreflightFix["target"]): string {
  switch (target) {
    case "install_harness":
      return "Install Claude CLI";
    case "sign_in":
      return "Sign in";
    case "add_api_key":
      return "Add API key";
    case "connect_host":
      return "Connect host";
    case "update_host":
      return "Update host";
    case "install_bwrap":
      return "Install bwrap";
    case "fix_workflow":
      return "Fix workflow";
    default: {
      const exhaustive: never = target;
      return exhaustive;
    }
  }
}

/** Settings path for fixes that open harness configuration. */
export function fixHref(target: PreflightFix["target"]): string | null {
  switch (target) {
    case "add_api_key":
    case "install_harness":
    case "sign_in":
      return "/settings/harnesses";
    default:
      return null;
  }
}

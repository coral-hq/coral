import { BRAIN_HARNESS_LABELS } from "@/lib/agentLabels";

// How Coral names a step's harness: the Claude harnesses by what people call them, the
// others as the chat composer names them, and an id this client does not know as itself.

const CORAL_HARNESS_LABELS: Readonly<Record<string, string>> = {
  "claude-sdk": "Claude",
  "claude-native": "Claude Code",
};

/** A harness id's display name; `null` when the step names none (the workspace default). */
export function harnessLabel(harness: string | null): string | null {
  if (harness === null || harness === "") return null;
  for (const labels of [CORAL_HARNESS_LABELS, BRAIN_HARNESS_LABELS]) {
    if (Object.hasOwn(labels, harness)) return labels[harness]!;
  }
  return harness;
}

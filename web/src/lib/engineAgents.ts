// CORAL(S54): engine step agents stay bound to their sessions but never appear in agent lists.
export function isEngineAgentName(name: string): boolean {
  return name.startsWith("coral__");
}

import type { CompiledGraph as GeneratedCompiledGraph, SimResult } from "../api/generated/coralApi";
import type { CompiledGraph } from "../api/workflowTypes";
import minimalCompiledJson from "./minimalCompiled.json";
import minimalYaml from "./minimal.yaml?raw";
import prReviewCompiledJson from "./prReviewCompiled.json";
import prReviewYaml from "./prReview.yaml?raw";
import reviewLoopSimulationsJson from "./reviewLoopSimulations.json";

export const MINIMAL_YAML: string = minimalYaml;
export const PR_REVIEW_YAML: string = prReviewYaml;
export const MINIMAL_COMPILED = minimalCompiledJson as unknown as CompiledGraph;
export const PR_REVIEW_COMPILED = prReviewCompiledJson as unknown as CompiledGraph;

// The "Implement with review loop" template's simulations, one per script in
// `tests/coral/api/simulate_contract.py`. Regenerate: `uv run --no-sync python -m
// tests.coral.api.simulate_contract --write`.
type ReviewLoopCase = "needs_review" | "needs_gate" | "approved" | "changes_to_limit";

export const REVIEW_LOOP_COMPILED =
  reviewLoopSimulationsJson.compiled as unknown as GeneratedCompiledGraph;
export const REVIEW_LOOP_SIMULATIONS = reviewLoopSimulationsJson.simulations as unknown as Readonly<
  Record<ReviewLoopCase, SimResult>
>;

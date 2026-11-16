import type { CompiledGraph } from "../api/workflowTypes";
import minimalCompiledJson from "./minimalCompiled.json";
import minimalYaml from "./minimal.yaml?raw";
import prReviewCompiledJson from "./prReviewCompiled.json";
import prReviewYaml from "./prReview.yaml?raw";

export const MINIMAL_YAML: string = minimalYaml;
export const PR_REVIEW_YAML: string = prReviewYaml;
export const MINIMAL_COMPILED = minimalCompiledJson as unknown as CompiledGraph;
export const PR_REVIEW_COMPILED = prReviewCompiledJson as unknown as CompiledGraph;

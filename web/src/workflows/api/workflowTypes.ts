/** Wire shapes for `/v1/coral/workflows*` (see `coral/api/workflows.py`). */

export type NodeKind = "start" | "end" | "step" | "decision" | "gate";
export type ArrowKind = "forward" | "back" | "at_limit" | "failure";

export interface CompiledNode {
  id: string;
  kind: NodeKind;
  name?: string | null;
  goal?: string | null;
  question?: string | null;
  prompt?: string | null;
  roster?: string[];
  harness?: string | null;
  attempts?: number | null;
  concurrency?: number | null;
  outcomes?: string[];
}

export interface CompiledArrow {
  id: string;
  source: string;
  target: string;
  label?: string | null;
  kind: ArrowKind;
  limit?: number | null;
  at_limit?: string | null;
}

/** Compiled IR; analysis is opaque to the desk. */
export interface CompiledGraph {
  ir_version: number;
  workflow_id: string;
  name: string;
  description?: string | null;
  nodes: CompiledNode[];
  arrows: CompiledArrow[];
  content_hash: string;
}

/** 1-based inclusive start, exclusive end. */
export interface SourceRange {
  start_line: number;
  start_column: number;
  end_line: number;
  end_column: number;
}

export type ProblemSeverity = "error" | "warning";

export interface Problem {
  rule: string;
  severity: ProblemSeverity;
  message: string;
  node_ids: string[];
  arrow_ids: string[];
  yaml_path: string | null;
  range: SourceRange | null;
}

export interface LoadIssue {
  yaml_path: string;
  range: SourceRange | null;
  message: string;
}

export interface LoadError {
  code: string;
  yaml_path: string;
  range: SourceRange | null;
  message: string;
  issues: LoadIssue[];
}

export interface ValidateResponse {
  valid: boolean;
  runnable: boolean;
  content_hash?: string;
  problems?: Problem[];
  compiled?: CompiledGraph;
  load_error?: LoadError;
}

export interface WorkflowSummary {
  id: string;
  workflow_key: string;
  name: string;
  content_hash: string;
  runnable: boolean;
  created_at: number;
  updated_at: number;
}

export interface WorkflowDetail extends WorkflowSummary {
  yaml: string;
  compiled: CompiledGraph;
}

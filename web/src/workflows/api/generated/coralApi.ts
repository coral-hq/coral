// Generated from coral/api/openapi.json by coral/omni/server/openapi_ts.py; do not edit.
// Regenerate with `just coral openapi`.

/** The body of a "mark as read": the empty JSON object. */
export type AckRequest = Record<string, never>;

export interface Analysis {
  checked_parts: CheckedPart[];
  join_types: JoinInfo[];
  label_sets: LabelSet[];
  loops: LoopInfo[];
  regions: Region[];
  unresolved: UnresolvedFact[];
}

/** Resolution of a ``list_from`` reference. */
export interface CheckedPart {
  node_id: string;
  part_is_list: boolean;
  part_name: string | null;
  reference: string;
  source_exists: boolean;
  source_node_id: string | null;
  source_upstream: boolean;
}

export interface CompiledArrow {
  at_limit: string | null;
  id: string;
  kind: "forward" | "back" | "at_limit" | "failure";
  label: string | null;
  limit: number | null;
  source: string;
  target: string;
}

export interface CompiledGraph {
  analysis: Analysis;
  arrows: CompiledArrow[];
  content_hash: string;
  description: string | null;
  ir_version: number;
  name: string;
  nodes: CompiledNode[];
  workflow_id: string;
}

export interface CompiledNode {
  attempts: number | null;
  concurrency: number | null;
  evidence: EvidenceRequirement | null;
  goal: string | null;
  harness: string | null;
  id: string;
  kind: "start" | "end" | "step" | "decision" | "gate";
  list_from: string | null;
  name: string | null;
  outcomes: string[];
  parts: CompiledPart[];
  prompt: string | null;
  question: string | null;
  roster: string[];
}

export interface CompiledPart {
  kind: "text" | "list";
  name: string;
}

/** What was refused: a stable ``code``, a message for people, and machine-readable details. */
export interface CoralError {
  code:
    | "unauthenticated"
    | "not_permitted"
    | "not_found"
    | "validation_failed"
    | "not_runnable"
    | "not_a_git_repo"
    | "start_key_conflict"
    | "workflow_key_taken"
    | "illegal_transition"
    | "stale_visit"
    | "worktree_failed"
    | "payload_too_large"
    | "stream_limit"
    | "not_implemented"
    | "host_offline"
    | "server_busy";
  details: Record<string, unknown> | null;
  message: string;
}

/** The body of every Coral refusal. */
export interface CoralErrorResponse {
  error: CoralError;
}

/** Response payload for ``GET /v1/coral/info``. */
export interface CoralInfoResponse {
  enabled: boolean;
  sub_features: Record<string, boolean>;
  version: string;
}

export interface EvidenceRequirement {
  ir_version: number;
  items: RequiredCommand[];
  scope: "per_agent";
}

/** A workflow document that did not load. */
export interface InvalidResult {
  load_error: LoadError;
  runnable: false;
  valid: false;
}

/** How a node with several incoming arrows combines them. */
export interface JoinInfo {
  arrow_ids: string[];
  join_type: "none" | "and" | "xor";
  node_id: string;
  split_node_id: string | null;
}

/** Labels on the label-selected outgoing arrows of a node. */
export interface LabelSet {
  labelled_arrow_ids: string[];
  labels: string[];
  node_id: string;
  unlabelled_arrow_ids: string[];
}

/** A document that could not be loaded; ``issues`` lists every schema error. */
export interface LoadError {
  code: string;
  issues: LoadIssue[];
  message: string;
  range: SourceRange | null;
  yaml_path: string;
}

export interface LoadIssue {
  message: string;
  range: SourceRange | null;
  yaml_path: string;
}

/** A loop closed by one back-arrow. */
export interface LoopInfo {
  at_limit_arrow_id: string | null;
  back_arrow_id: string;
  body: string[];
  entry_arrow_ids: string[];
  head: string;
  limit: number | null;
  tail: string;
}

/** One finding, anchored to nodes, arrows and a ``yaml_path``. */
export interface Problem {
  arrow_ids: string[];
  message: string;
  node_ids: string[];
  range: SourceRange | null;
  rule: string;
  severity: "error" | "warning" | "info";
  yaml_path: string | null;
}

/** Parallel region between an unlabelled split and its AND-join. */
export interface Region {
  join_node_id: string;
  node_ids: string[];
  split_node_id: string;
}

/**
 * One command that must pass after the step's last change.
 *
 * :param run: One plain command, e.g. ``pytest -q``, matched as the last command
 *     of an ``&&`` chain (``coral.evidence.match``).
 * :param may_modify: The command may change the tree (a formatter); its own
 *     changes do not count as the step's last change when it runs on its own.
 * :param allow_args: A run may add arguments after ``run``; by default the
 *     argv must be exactly ``run``'s.
 */
export interface RequiredCommand {
  allow_args: boolean;
  item_id: string;
  may_modify: boolean;
  run: string;
}

/** The definition a save stored, with the validation of what was saved. */
export interface SavedWorkflowOut {
  compiled: CompiledGraph;
  content_hash: string;
  created_at: number;
  id: string;
  name: string;
  problems: Problem[];
  runnable: boolean;
  updated_at: number;
  valid: true;
  workflow_key: string;
}

/** 1-based inclusive start, exclusive end positions in the YAML text. */
export interface SourceRange {
  end_column: number;
  end_line: number;
  start_column: number;
  start_line: number;
}

/** Something Analysis could not resolve; blocks running the workflow. */
export interface UnresolvedFact {
  arrow_ids: string[];
  code: string;
  message: string;
  node_ids: string[];
}

/** A workflow that loaded and compiled, with what validation found. */
export interface ValidResult {
  compiled: CompiledGraph;
  content_hash: string;
  problems: Problem[];
  runnable: boolean;
  valid: true;
}

/** One open alert as the Inbox lists it: its row's fields merged with its payload. */
export interface WorkflowAlertOut {
  actions: ("answer" | "open_run" | "mark_read" | "resume" | "cancel")[];
  alert_id: string;
  approve_link: string | null;
  created_at: number;
  deep_link: string;
  elicitation_id: string | null;
  kind:
    | "gate"
    | "question"
    | "pause"
    | "watchdog"
    | "overdue"
    | "reaction"
    | "run_completed"
    | "run_failed"
    | "run_cancelled";
  message: string;
  node_id: string | null;
  outcomes: string[];
  pause_reason: string | null;
  priority: "normal" | "low";
  run_id: string;
  run_title: string;
  session_id: string | null;
  step_label: string | null;
  title: string;
}

/** A stored workflow definition with its YAML and compiled graph. */
export interface WorkflowDetailOut {
  compiled: CompiledGraph;
  content_hash: string;
  created_at: number;
  id: string;
  name: string;
  runnable: boolean;
  updated_at: number;
  workflow_key: string;
  yaml: string;
}

/**
 * One feed page. A page can be empty and still carry ``next_cursor``: keep paging
 * until it is null.
 */
export interface WorkflowInboxPage {
  data: WorkflowAlertOut[];
  next_cursor: string | null;
}

/** A stored workflow definition as lists show it. */
export interface WorkflowSummaryOut {
  content_hash: string;
  created_at: number;
  id: string;
  name: string;
  runnable: boolean;
  updated_at: number;
  workflow_key: string;
}

/** A workflow document as YAML text. */
export interface WorkflowYaml {
  yaml: string;
}

/**
 * Every Coral operation by its operationId.
 * Each status in `errors` answers a `CoralErrorResponse` body.
 */
export interface CoralOperations {
  /**
   * GET /v1/coral/inbox
   *
   * The caller's open alerts: normal priority first, newest first within each.
   */
  coral_list_inbox: {
    method: "GET";
    path: "/v1/coral/inbox";
    query: {
      after?: string | null;
      limit?: number;
    };
    status: 200;
    response: WorkflowInboxPage;
    errors: 401 | 403 | 404 | 422;
  };
  /**
   * POST /v1/coral/inbox/{alert_id}/ack
   *
   * Mark one of the caller's alerts read; marking it again changes nothing.
   */
  coral_ack_alert: {
    method: "POST";
    path: "/v1/coral/inbox/{alert_id}/ack";
    params: {
      alert_id: string;
    };
    body: AckRequest;
    status: 204;
    response: null;
    errors: 401 | 403 | 404 | 409 | 422;
  };
  /**
   * GET /v1/coral/info
   *
   * Report whether Coral is enabled on this server and its sub-feature map.
   */
  coral_get_info: {
    method: "GET";
    path: "/v1/coral/info";
    status: 200;
    response: CoralInfoResponse;
  };
  /**
   * GET /v1/coral/workflows
   *
   * The caller's workflows, by key.
   */
  coral_list_workflows: {
    method: "GET";
    path: "/v1/coral/workflows";
    status: 200;
    response: WorkflowSummaryOut[];
    errors: 401 | 403;
  };
  /**
   * POST /v1/coral/workflows
   *
   * Store the caller's workflow under its key, replacing their earlier version.
   */
  coral_save_workflow: {
    method: "POST";
    path: "/v1/coral/workflows";
    body: WorkflowYaml;
    status: 200;
    response: SavedWorkflowOut;
    errors: 401 | 403 | 409 | 413 | 422;
  };
  /**
   * GET /v1/coral/workflows/{workflow_id}
   *
   * One of the caller's workflows with its YAML and compiled graph.
   */
  coral_get_workflow: {
    method: "GET";
    path: "/v1/coral/workflows/{workflow_id}";
    params: {
      workflow_id: string;
    };
    status: 200;
    response: WorkflowDetailOut;
    errors: 401 | 403 | 404 | 422;
  };
  /**
   * POST /v1/coral/workflows:validate
   *
   * Load, compile and validate a workflow without storing it.
   */
  coral_validate_workflow: {
    method: "POST";
    path: "/v1/coral/workflows:validate";
    body: WorkflowYaml;
    status: 200;
    response: ValidResult | InvalidResult;
    errors: 401 | 403 | 422;
  };
}

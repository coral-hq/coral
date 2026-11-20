// Generated from coral/api/openapi.json by coral/omni/server/openapi_ts.py; do not edit.
// Regenerate with `just coral openapi`.

/** The body of a "mark as read": the empty JSON object. */
export type AckRequest = Record<string, never>;

export interface ActivationView {
  id: string;
  outcome: "completed" | "skipped" | "failed" | null;
  status: "waiting_join" | "ready" | "starting" | "running" | "evaluating" | "closed";
}

export interface Analysis {
  checked_parts: CheckedPart[];
  join_types: JoinInfo[];
  label_sets: LabelSet[];
  loops: LoopInfo[];
  regions: Region[];
  unresolved: UnresolvedFact[];
}

/** How many alerts a bulk mark-as-read changed; 0 for another user's or an unknown run. */
export interface BulkAckOut {
  acked: number;
}

/** The body of marking a run's low-priority alerts read: the run's id. */
export interface BulkAckRequest {
  run_id: string;
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

/** The body of an action that takes no arguments: the empty JSON object. */
export type EmptyRequest = Record<string, never>;

/** One run-log row without its body; ``patch`` is the stored view patch, or empty. */
export interface EntryFrame {
  actor: string | null;
  actor_kind: "engine" | "orchestrator" | "step_agent" | "user" | "simulator";
  at_us: number;
  kind: string;
  node_id: string | null;
  patch: JsonPatch[];
  rejected: string | null;
  run_version: number;
  scope_key: string | null;
  seq: number;
  type: "entry";
}

export interface EvidenceRequirement {
  ir_version: number;
  items: RequiredCommand[];
  scope: "per_agent";
}

/** A taken answer; ``duplicate`` when the same answer was taken before. */
export interface GateAnswerOut {
  result: "accepted" | "duplicate";
}

/** An answer to one visit of a gate: the visit's token, the chosen outcome and a note. */
export interface GateAnswerRequest {
  note?: string;
  outcome: string;
  visit_token: string;
}

/**
 * A gate visit waiting for its answer. ``context`` is what its approval prompt asks;
 * ``None`` when the run's engine state cannot be loaded or does not hold the visit.
 */
export interface GateOut {
  context: string | null;
  elicitation_id: string | null;
  node_id: string;
  opened_at: number;
  outcomes: string[];
  token: string;
  visit_id: string;
  visit_no: number;
}

export interface HeartbeatFrame {
  type: "heartbeat";
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

/** One JSON Patch operation addressed by a JSON pointer. */
export interface JsonPatch {
  op: "add" | "remove" | "replace";
  path: string;
  value: JsonValue | null;
}

export type JsonValue = unknown;

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

/**
 * One run-log row with its body: the stream's entry frame plus ``body``. ``body`` is
 * ``None`` for a row that cannot be read (``kind`` ``log.unreadable``) and, with
 * ``body_truncated``, for a body too large to send. ``actor_kind`` is ``None`` only on
 * such a row, for a code this server does not know.
 */
export interface LogEntryOut {
  actor: string | null;
  actor_kind: "engine" | "orchestrator" | "step_agent" | "user" | "simulator" | null;
  at_us: number;
  body: Record<string, JsonValue> | null;
  body_truncated: boolean;
  kind: string;
  node_id: string | null;
  patch: JsonPatch[];
  rejected: string | null;
  run_version: number;
  scope_key: string | null;
  seq: number;
  type: "entry";
}

/** Log rows in ``seq`` order; ``next_after_seq`` is set when more rows follow. */
export interface LogPage {
  data: LogEntryOut[];
  next_after_seq: number | null;
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

export interface LoopPassView {
  back_arrow_id: string;
  item_path: string[];
  iteration_path: string[];
  pass_index: number;
}

export interface PauseCause {
  detail: string;
  reason:
    | "auth"
    | "plan_limit"
    | "infra"
    | "budget"
    | "liveness"
    | "failure_path"
    | "drift"
    | "rejected_calls"
    | "authority_revoked"
    | "engine_upgrade"
    | "user";
  subject: string;
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

/** A resume; ``cap`` raises the activation cap of a run paused at it. */
export interface ResumeRequest {
  cap?: number | null;
}

/** The cursor cannot be replayed; a fresh ``snapshot`` follows. */
export interface ResyncFrame {
  reason: "cursor_unknown" | "cursor_invalid" | "replay_too_long" | "row_unreadable";
  type: "resync";
}

/**
 * One run in full. ``view`` is ``None`` and ``load_error`` is set for a run that
 * cannot be loaded; ``target``, ``max_activations`` and ``request_preview`` are
 * ``None`` when its stored rows cannot be read.
 */
export interface RunDetail {
  activation_count: number;
  allowed_actions: ("pause" | "resume" | "cancel")[];
  anchor_session_id: string;
  causes: PauseCause[];
  created_at: number;
  finished_at: number | null;
  gates: GateOut[];
  head_seq: number;
  load_error: "engine.load_failed" | null;
  max_activations: number | null;
  orchestrator_session_id: string | null;
  pause_reason:
    | "gate"
    | "budget"
    | "plan_limit"
    | "rejected_calls"
    | "infra"
    | "liveness"
    | "user"
    | "authority_revoked"
    | "merge_conflict"
    | "failure_path"
    | "engine_upgrade"
    | "drift"
    | "auth"
    | null;
  request_preview: string | null;
  run_branch: string;
  run_id: string;
  slots: SlotOut[];
  spend: RunSpend | null;
  status: "starting" | "running" | "paused" | "completed" | "failed" | "cancelled";
  target: RunTarget | null;
  title: string;
  updated_at: number;
  version: number;
  version_id: string;
  view: RunView | null;
  workflow_id: string;
}

/** The run header again, sent when the row changes without a view patch. */
export interface RunFrame {
  allowed_actions: ("pause" | "resume" | "cancel")[];
  finished_at: number | null;
  load_error: "engine.load_failed" | null;
  pause_reason:
    | "gate"
    | "budget"
    | "plan_limit"
    | "rejected_calls"
    | "infra"
    | "liveness"
    | "user"
    | "authority_revoked"
    | "merge_conflict"
    | "failure_path"
    | "engine_upgrade"
    | "drift"
    | "auth"
    | null;
  status: "starting" | "running" | "paused" | "completed" | "failed" | "cancelled";
  type: "run";
  version: number;
}

/** The run row as clients see it; a finished row wins over what the view says. */
export interface RunHeader {
  allowed_actions: ("pause" | "resume" | "cancel")[];
  finished_at: number | null;
  load_error: "engine.load_failed" | null;
  pause_reason:
    | "gate"
    | "budget"
    | "plan_limit"
    | "rejected_calls"
    | "infra"
    | "liveness"
    | "user"
    | "authority_revoked"
    | "merge_conflict"
    | "failure_path"
    | "engine_upgrade"
    | "drift"
    | "auth"
    | null;
  status: "starting" | "running" | "paused" | "completed" | "failed" | "cancelled";
  version: number;
}

/** One page of runs, newest first; page again with ``next_cursor`` until it is null. */
export interface RunPage {
  data: RunSummary[];
  next_cursor: string | null;
}

/**
 * What a run has spent so far, as last read: shown, never capped.
 *
 * ``usd`` is the display figure its anchor's badge shows, ``live_usd`` includes
 * spend still in flight; both are ``None`` when no session was priced and a lower
 * bound when ``unpriced_models`` is not empty. ``as_of`` is when it was read.
 */
export interface RunSpend {
  as_of: number;
  estimate: true;
  live_usd: number | null;
  sessions: number;
  tokens: RunSpendTokens;
  unpriced_models: string[];
  usd: number | null;
}

/** Tokens a run's sessions used, summed over its whole session tree. */
export interface RunSpendTokens {
  cache_creation: number;
  cache_read: number;
  input: number;
  output: number;
  total: number;
}

export type RunStreamFrame = SnapshotFrame | EntryFrame | RunFrame | ResyncFrame | HeartbeatFrame;

/** A run as its owner's run list shows it; ``run_branch`` is derived from its id. */
export interface RunSummary {
  activation_count: number;
  allowed_actions: ("pause" | "resume" | "cancel")[];
  created_at: number;
  finished_at: number | null;
  pause_reason:
    | "gate"
    | "budget"
    | "plan_limit"
    | "rejected_calls"
    | "infra"
    | "liveness"
    | "user"
    | "authority_revoked"
    | "merge_conflict"
    | "failure_path"
    | "engine_upgrade"
    | "drift"
    | "auth"
    | null;
  run_branch: string;
  run_id: string;
  spend: RunSpend | null;
  status: "starting" | "running" | "paused" | "completed" | "failed" | "cancelled";
  title: string;
  updated_at: number;
  version_id: string;
  workflow_id: string;
}

/** Where the run works: its host, repository and worktree branch. */
export interface RunTarget {
  base_commit: string | null;
  base_ref: string | null;
  host_id: string | null;
  repo_path: string | null;
  run_branch: string | null;
  worktree_path: string | null;
}

export interface RunView {
  activations: ActivationView[];
  armed_timer_keys: string[];
  causes: PauseCause[];
  loop_pass_indexes: LoopPassView[];
  open_decisions: string[];
  open_gates: string[];
  slots: SlotView[];
  status: "running" | "paused" | "completed" | "failed" | "cancelled" | null;
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

/**
 * An agent slot of one of the run's steps. ``slot_id`` and ``activation_id`` are store
 * ids; ``engine_slot_id`` is the id the run view's slots carry.
 */
export interface SlotOut {
  activation_id: string;
  engine_slot_id: string;
  node_id: string;
  role: "step_agent" | "orchestrator" | "verifier" | "merge_resolver";
  session_generation: number;
  session_id: string | null;
  slot_id: string;
  status:
    | "pending"
    | "session_created"
    | "briefed"
    | "working"
    | "handoff_accepted"
    | "rejected"
    | "refreshing"
    | "restarting"
    | "closed"
    | "evaluating"
    | "closing";
}

export interface SlotView {
  drift: boolean;
  id: string;
  pending_input: boolean;
  status:
    "pending" | "session_created" | "briefed" | "working" | "evaluating" | "closing" | "closed";
}

/** The whole view at head ``seq``; ``view`` is ``None`` only for a run that cannot load. */
export interface SnapshotFrame {
  log_version: number;
  protocol: 1;
  run: RunHeader;
  run_version: number;
  seq: number;
  type: "snapshot";
  view: RunView | null;
  view_error: "engine.load_failed" | null;
  view_version: 1;
}

/** 1-based inclusive start, exclusive end positions in the YAML text. */
export interface SourceRange {
  end_column: number;
  end_line: number;
  start_column: number;
  start_line: number;
}

/**
 * A start of one of the caller's workflows on their host's repository.
 *
 * ``start_key`` makes the start idempotent: the same key and request answer the run
 * it started, another request with the key is a conflict. ``title`` defaults to the
 * workflow's name; ``base_ref`` to the repository's checked-out head.
 */
export interface StartRunRequest {
  base_ref?: string | null;
  host_id: string;
  max_activations?: number;
  repo_path: string;
  request?: string;
  start_key: string;
  title?: string | null;
  workflow_id: string;
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
   * POST /v1/coral/inbox/ack
   *
   * Mark the caller's open low-priority alerts of one run read, as opening the run
   * does. Alerts that ask for an action or an answer stay open.
   */
  coral_ack_alerts: {
    method: "POST";
    path: "/v1/coral/inbox/ack";
    body: BulkAckRequest;
    status: 200;
    response: BulkAckOut;
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
   * GET /v1/coral/runs
   *
   * The caller's runs, newest first; spend is what the cache holds, or null.
   */
  coral_list_runs: {
    method: "GET";
    path: "/v1/coral/runs";
    query: {
      after?: string | null;
      limit?: number;
      status?: ("starting" | "running" | "paused" | "completed" | "failed" | "cancelled")[];
      workflow_id?: string | null;
    };
    status: 200;
    response: RunPage;
    errors: 401 | 403 | 404 | 422 | 503;
  };
  /**
   * POST /v1/coral/runs
   *
   * Start one of the caller's workflows on their host's repository: 201 with the new
   * run, or 200 with the run the same ``start_key`` and request started before.
   */
  coral_start_run: {
    method: "POST";
    path: "/v1/coral/runs";
    body: StartRunRequest;
    status: 200 | 201;
    response: RunSummary;
    errors: 400 | 401 | 403 | 404 | 409 | 422 | 503;
  };
  /**
   * GET /v1/coral/runs/{run_id}
   *
   * One of the caller's runs in full, with its spend so far.
   */
  coral_get_run: {
    method: "GET";
    path: "/v1/coral/runs/{run_id}";
    params: {
      run_id: string;
    };
    status: 200;
    response: RunDetail;
    errors: 401 | 403 | 404 | 422 | 503;
  };
  /**
   * POST /v1/coral/runs/{run_id}/activations/{activation_id}:retry
   *
   * Not served yet: the caller's own run answers 501.
   */
  coral_retry_activation: {
    method: "POST";
    path: "/v1/coral/runs/{run_id}/activations/{activation_id}:retry";
    params: {
      activation_id: string;
      run_id: string;
    };
    body: EmptyRequest;
    status: never;
    response: never;
    errors: 401 | 403 | 404 | 422 | 501 | 503;
  };
  /**
   * POST /v1/coral/runs/{run_id}/gates/{node_id}:answer
   *
   * Answer a visit of one of the caller's run's gates with one of its outcomes, as
   * its prompt would be answered. A visit the run does not have is the run 404.
   */
  coral_answer_gate: {
    method: "POST";
    path: "/v1/coral/runs/{run_id}/gates/{node_id}:answer";
    params: {
      node_id: string;
      run_id: string;
    };
    body: GateAnswerRequest;
    status: 200;
    response: GateAnswerOut;
    errors: 401 | 403 | 404 | 409 | 422 | 503;
  };
  /**
   * GET /v1/coral/runs/{run_id}/graph
   *
   * The workflow graph the run is pinned to; ``If-None-Match`` revalidates it.
   */
  coral_get_run_graph: {
    method: "GET";
    path: "/v1/coral/runs/{run_id}/graph";
    params: {
      run_id: string;
    };
    status: 200;
    response: CompiledGraph;
    errors: 401 | 403 | 404 | 422 | 503;
  };
  /**
   * GET /v1/coral/runs/{run_id}/log
   *
   * The run's log rows after ``after_seq``, with their bodies: at most 1 MiB of bodies
   * and patches a page, then ``next_after_seq``. A body over 256 KiB is left out.
   */
  coral_get_run_log: {
    method: "GET";
    path: "/v1/coral/runs/{run_id}/log";
    params: {
      run_id: string;
    };
    query: {
      after_seq?: number;
      limit?: number;
    };
    status: 200;
    response: LogPage;
    errors: 401 | 403 | 404 | 422 | 503;
  };
  /**
   * GET /v1/coral/runs/{run_id}/outcome
   *
   * Not served yet: the caller's own run answers 501.
   */
  coral_get_run_outcome: {
    method: "GET";
    path: "/v1/coral/runs/{run_id}/outcome";
    params: {
      run_id: string;
    };
    status: never;
    response: never;
    errors: 401 | 403 | 404 | 422 | 501 | 503;
  };
  /**
   * GET /v1/coral/runs/{run_id}/stream
   *
   * Follow one of the caller's runs: a snapshot of its view, then one entry per log
   * row with the row's view patch. ``Last-Event-ID`` (else ``after_seq``) resumes
   * after the last seq the client holds. A stream ends after five minutes; the
   * client resumes from its last seq. Past the stream caps, poll ``/log`` instead.
   */
  coral_stream_run: {
    method: "GET";
    path: "/v1/coral/runs/{run_id}/stream";
    params: {
      run_id: string;
    };
    query: {
      after_seq?: number | null;
    };
    status: 200;
    response: never;
    /** Server-sent events: each event's `data` is one of these, or `[DONE]` at the end. */
    events: RunStreamFrame;
    errors: 401 | 403 | 404 | 422 | 429 | 503;
  };
  /**
   * POST /v1/coral/runs/{run_id}:cancel
   *
   * Cancel one of the caller's runs; a cancelled run is left as it is.
   */
  coral_cancel_run: {
    method: "POST";
    path: "/v1/coral/runs/{run_id}:cancel";
    params: {
      run_id: string;
    };
    body: EmptyRequest;
    status: 200;
    response: RunSummary;
    errors: 401 | 403 | 404 | 409 | 422 | 503;
  };
  /**
   * POST /v1/coral/runs/{run_id}:pause
   *
   * Pause one of the caller's runs; a paused run is left as it is.
   */
  coral_pause_run: {
    method: "POST";
    path: "/v1/coral/runs/{run_id}:pause";
    params: {
      run_id: string;
    };
    body: EmptyRequest;
    status: 200;
    response: RunSummary;
    errors: 401 | 403 | 404 | 409 | 422 | 503;
  };
  /**
   * POST /v1/coral/runs/{run_id}:resume
   *
   * Resume one of the caller's paused runs; ``cap`` raises the activation cap of one
   * paused at it. A run not paused is left as it is.
   */
  coral_resume_run: {
    method: "POST";
    path: "/v1/coral/runs/{run_id}:resume";
    params: {
      run_id: string;
    };
    body: ResumeRequest;
    status: 200;
    response: RunSummary;
    errors: 401 | 403 | 404 | 409 | 422 | 503;
  };
  /**
   * POST /v1/coral/runs:preflight
   *
   * Not served yet.
   */
  coral_preflight_run: {
    method: "POST";
    path: "/v1/coral/runs:preflight";
    body: EmptyRequest;
    status: never;
    response: never;
    errors: 401 | 403 | 422 | 501;
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

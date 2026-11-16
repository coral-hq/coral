<!-- CORAL(S77): Coral's summary of its changes to Omnigent files -->
# Coral modifications

This file supplements the `CORAL(<seam id>)` notices that the Apache License,
Version 2.0, section 4(b), requires in each file Coral modifies: every changed
Omnigent file carries a one-line `CORAL(<seam id>)` comment at the change, and
this table lists each such file with its seams and what changed. Files that the
brand transform `.coral/tools/rebrand.py` rewrites (seam S95) carry one anchor
at the top instead, and the script defines each change. For files that
cannot carry a comment (JSON, lockfiles, images and other binaries, generated
files) this table is the only record, which is a question for counsel (OPS-05).
The seams are defined in [`.coral/seams.yaml`](.coral/seams.yaml).
OPS-01's generator will maintain this file later.

| File | Seams | Category | Change |
|---|---|---|---|
| `.github/CODEOWNERS` | S39 | coral-specific | Appends Coral's ownership block for `/coral/`, `/coral/db/migrations/`, `/docs/coral/`, and `/.coral/` below Omnigent's unchanged lines (S39). |
| `.github/ISSUE_TEMPLATE/bug_report.yml` | S94 | coral-specific | The version field asks for the Coral commit. |
| `.github/ISSUE_TEMPLATE/config.yml` | S94 | coral-specific | The contact links point to Coral's Discussions and documentation. |
| `.github/dependabot.yml` | S100 | coral-specific | Every update entry is off for now (limit 0, ignores every dependency); Coral takes dependency updates from Omnigent's upstream syncs. |
| `.github/scripts/ci/python-matrix.json` | S39d | coral-specific | Adds the `coral` shard (`tests/coral`) and ignores `tests/coral` in `misc` (S39d). |
| `.github/workflows/ci.yml` | S99, S39c | coral-specific | Runs after merges to `development`, Coral's integration branch, as well as `main` (S99). Collects coverage for `coral` alongside `omnigent` (S39c). |
| `.github/workflows/lint.yml` | S99 | coral-specific | Runs after merges to `development`, Coral's integration branch, as well as `main`. |
| `.github/workflows/security-gate.yml` | S99 | coral-specific | Reads its trust rules from the default branch (`development`) instead of `main`. |
| `.github/workflows/security-scan.yml` | S99 | coral-specific | Reads its trust rules from the default branch (`development`) instead of `main`. |
| `.github/workflows/web-tests.yml` | S99 | coral-specific | Runs after merges to `development`, Coral's integration branch, as well as `main`. |
| `.gitignore` | S77 | coral-specific | Tracks `.coral/` despite the `.*/` rule. |
| `.pre-commit-config.yaml` | S93, S101, S39e | coral-specific | Exempts the committed 1.2 MB Coral roadmap from `check-added-large-files` (S93); the pyrefly hook checks against the checkout's own `.venv` interpreter, so worktrees that inherit another `VIRTUAL_ENV` pass (S101); triggers pyrefly on `coral/` changes (S39e). |
| `CONTRIBUTING.md` | S94 | coral-specific | Retitled for Coral, with a note on seams in Omnigent files and Coral's branch flow (`development` is the default branch; releases merge into `main` and back); the clone URL and bug-report field point to Coral. |
| `MODIFICATIONS.md` | S77 | coral-specific | Added. This file. |
| `NOTICE` | S77 | coral-specific | Appends the Coral addendum after Omnigent's unchanged NOTICE: Coral's copyright, the attribution to Omnigent, the CORAL anchor rule, and notices for fonts Coral adds or newly documents. |
| `README.md` | S91 | coral-specific | Replaced by Coral's README: what Coral is, its status, running it from source with `coral start` (the `coral` command wraps the same CLI as `omnigent`), documentation, contributing, and the credit and attribution to Omnigent. |
| `SECURITY.md` | S94 | coral-specific | Vulnerability reports go to Coral's private security advisories or coralai.team@gmail.com; the code-scanning link points to Coral's repository. |
| `deploy/databricks/src/app.py` | S57 | upstream-extension | Runs Coral schema migrations with retry strictly after Omnigent migrations at startup (S57). |
| `dev/lint/custom_lint.py` | S39 | coral-specific | Registers the `coral-import-boundary` rule last in `RULES` (S39). |
| `dev/lint/lint_coral_import_boundary.py` | S39, S58 | coral-specific | Added. Enforces Coral's pure/omni/db/app/root three-tier import boundaries (S39). Allowlist permits shared Omnigent DB utilities in coral.db (S58). Marks `coral.signals` as pure so the workflow reducer can import the outbox table. |
| `dev/lint/lint_workspace_scoped_cache.py` | S39 | coral-specific | Adds `coral/` to `SCANNED_ROOTS` (S39). |
| `justfile` | S87, S76 | coral-specific | `electron-run` finds, quits and resets the "Coral Dev" build, and `electron-mdm` writes and imports Coral's app-id preference domains (S87). Mounts `mod coral 'coral/coral.just'` (S76). |
| `omnigent/chat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/cli.py` | S96, S95, S32 | upstream-extension | The crash handler shows Coral and files issues on coral-hq/coral (S96). Passes configured `server_plugins` into `create_app` (S32). Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/cli_config.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/cli_diagnostics.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/cli_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/cli_sandbox.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/conversation_browser.py` | S38, S95 | coral-specific | `deep_link_url` generates `coral://` links for `--open-in-desktop` (S38). Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/crash_handler.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/db/cockroachdb.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/db/enum_codecs.py` | S58 | upstream-extension | Public encode_enum and decode_enum helpers for Coral schema codecs (S58). |
| `omnigent/db/migrations/env.py` | S30 | upstream-extension | Filters out Coral tables (coral_*) and coral_alembic_version from Omnigent Alembic autogenerate (S30). |
| `omnigent/db/pagination.py` | S58 | upstream-extension | Added. Shared keyset_after pagination helper with MySQL scalar expansion (S58). |
| `omnigent/db/utils.py` | S95, S58 | upstream-extension | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Exposes create_db_engine and get_db_revision_state for isolated Coral schema checks (S58). |
| `omnigent/extensions/registry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/antigravity_native/bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/antigravity_native/reader.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/claude_native/bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/claude_native/forwarder.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/claude_native/hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/claude_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/codex_native/app_server.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/codex_native/forwarder.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/codex_native/hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/codex_native/launch_args.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/codex_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/cursor_native/bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/cursor_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/devin_native/bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/devin_native/hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/devin_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/goose_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/hermes_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/kimi_native/credentials.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/kimi_native/hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/kimi_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/kiro_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/opencode_native/bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/opencode_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/opencode_native/provider.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/pi_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/harnesses/qwen_native/main.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/_daemon_entry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/connect.py` | S71, S72, S95, S40 | upstreamable, coral-specific | The fs request, fs write, skills, skill-content and credential-detection frames and the worktree create/remove/list handlers run through `_run_host_subprocess_in_thread`, so the orphan reaper cannot steal their children's exit statuses and stays paused until a cancelled frame's worker exits; the host builds its workspace readers with `start_registry=False` (S71). The create-worktree reply carries the new worktree's `head_commit`, and each listed worktree carries `locked` (S72). Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. A `host.workspace_op` frame runs its handler through `dispatch_workspace_op` inside `_run_host_subprocess_in_thread`, at most two at once per host (a semaphore taken before the guard), and is answered with `host.workspace_op_result`; the handlers are read through the `workspace_ops` module, so a patch takes effect (S40). |
| `omnigent/host/frames.py` | S72, S40 | upstreamable, coral-specific | `host.create_worktree_result` gains an optional `head_commit` string; an absent key decodes to `None`, with no capability token (S72). `HOST_CAPABILITIES` advertises `workspace_ops:1`; `HostFrame` includes the workspace-op request and result, and `encode_host_frame` and `decode_host_frame` route the two kinds to `omnigent.host.workspace_ops` (S40). |
| `omnigent/host/git_worktree.py` | S72 | upstreamable | `CreatedWorktree.head_commit` reports the new worktree's HEAD, read with the create's deadline-aware git helper after the worktree is complete; a failed read logs a warning and gives `None` without rolling back, and a pinned checkout reuses its validated commit. `list_worktrees` parses git's porcelain `locked` / `locked <reason>` line into `WorktreeInfo.locked` (S72). |
| `omnigent/host/service.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/service_entry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/workspace_ops.py` | S40, S40b | coral-specific | Added. The `host.workspace_op` and `host.workspace_op_result` frames, their codec (typed fields, `timeout_s` in (0, 900], an ok result needs a payload and a failed one a code, an absent `permanent` reads `False`), the `workspace_ops:1` token, and the root and op-key checks shared with the server. `dispatch_workspace_op` always answers: `unknown_op` or `invalid_request` (permanent, before any handler runs); otherwise at most two ops per host run inside the caller's reaper guard with a deadline, the payload is serialised once in the worker and capped at 8 MiB (`invalid_payload` and `result_too_large` are permanent), a typed handler error keeps its checked fields (message trimmed to 2,000 characters), and anything else is `handler_failed` with its type name only (S40). Handlers load lazily, once per process, from `omnigent.host_workspace_ops` entry points: a broken contribution is skipped whole, an op offered by two packages is served by neither (logged as an error), each served op is logged with its package, and `unknown_op` says when a handler failed to load (S40b). |
| `omnigent/inner/_acp_omnigent_mcp.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/claude_sdk_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/codex_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/codex_native_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/copilot_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/cursor_policy_hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/egress/ca.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/hermes_policy_hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/hook_scripts/subagent_router.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/kimi_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/pi_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/policies.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/terminal.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/terminal_clipboard.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/models/model_fallbacks.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/native/native_cost_popup.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/native/native_policy_hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/native/native_terminal.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/configure_models.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/harness_install.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/sandboxes/base.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/sandboxes/blaxel.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/sandboxes/bootstrap.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/sandboxes/e2b.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/secrets.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/setup.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/onboarding/ucode_setup.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/policies/builtins/github.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/policies/builtins/orchestration.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/policies/builtins/safety.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/policies/builtins/working_dir.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/repl/_repl.py` | S96 | coral-specific | `/bug` opens an issue on coral-hq/coral. |
| `omnigent/resume_dispatch.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/app.py` | S95, S43 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Turn-end status edges (stream end, cancelled drain, desync and session-init failures) carry `turn_outcome` (`completed`, `cancelled` or `failed`) and, when known, `turn_response_id` (the ended response), read before the live response is released; sign-in holds and the native drop rules publish none. A turn whose stream ends with buffered input carries its outcome to the next turn start's `running` edge, or to an `idle` edge when the drain finds the queue gone; a force-cancelled interrupt reports it on the drain's `idle` instead. Deleting a session drops a carried outcome; `app.state.carried_turn_outcomes` is a test seam (S43). |
| `omnigent/runner/background_titles/claude_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/git_providers/azure_devops.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/git_providers/gitlab.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/launch_failure.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/mcp_manager.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/native/orchestration.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/policy_proxy.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runner/tool_dispatch.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runtime/__init__.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runtime/harnesses/_executor_adapter.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runtime/harnesses/process_manager.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runtime/prompt.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/runtime/subagent_block_notifier.py` | S51 | upstreamable | A blocked child labelled `omnigent.parent_wake: off` (exact match, read after the grace) does not wake its parent; the block stays debounced until it resolves and no resolution notice is sent (S51). |
| `omnigent/runtime/workflow.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/app.py` | S95, S32, S41 | upstream-extension | Wires `server_plugins` loading, router mounting ahead of `_SPAStaticFiles`, policy-module merging, and lifespan hook execution (S32). Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. The session event handler is always kept on `app.state.session_event_dispatch` for in-process senders, typed as `SessionEventDispatch`, and still handed to managed startup inputs when they exist (S41). |
| `omnigent/server/host_registry.py` | S40 | coral-specific | `HostConnection.pending_workspace_ops` holds workspace-op requests and fails them with the worktree requests when the connection is replaced or deregistered; `host_owner_scope` records that it is active, and `host_owner_scope_matches` tells whether the active scope names a connection's owner, workspace and registration (an ownerless scope matches only an ownerless connection) (S40). |
| `omnigent/server/mcp_compatibility.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/performance_metrics.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_host_workspace_ops.py` | S40 | coral-specific | Added. Before a frame is sent, `request_workspace_op_on_host` refuses a host without `workspace_ops:1`, any frame the host would drop or refuse (the shared codec, root and op-key checks), and any send outside a `host_owner_scope` naming the connection's owner registration. It then awaits the result through `_await_host_worktree_result` for `timeout_s` + 15 s. `WorkspaceOpReply` carries the six result fields, with the host's error text cut to 2,000 characters and a malformed code read as `handler_failed`; `HostWorkspaceOpUnavailableError.timed_out` tells a timeout from a lost connection, and both leave the outcome unknown (S40). |
| `omnigent/server/routes/_host_worktree.py` | S72 | upstreamable | The server's `CreatedWorktree` gains `head_commit`, kept from the host result only when it is a full git object id (40 or 64 lowercase hex) and `None` otherwise (S72). |
| `omnigent/server/routes/_session_harness_readiness.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_sessions/common.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_sessions/helpers.py` | S95, S1 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. `_publish_status` takes keyword-only `origin`, `turn_outcome` and `turn_response_id` and notifies status-edge observers once, after the stream publish; nothing is added to the stream payload or the caches (S1). |
| `omnigent/server/routes/_sessions/orchestration.py` | S95, S1, S43 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Status-edge origins and turn outcomes: the stop and archive settlement, the offline sweep's stop settlement and the relay's stop idle report `cancelled` with the turn's response id only while the session is still `running` at the publish (shared `_stopped_turn`); only the archived session itself carries `archive_idle`; the relay disconnect reports `failed` with its turn's id and origin `runner_disconnect`; the offline sweep's mid-turn failure reports `failed` with its turn id when one is known; the runner-recovered status (with `relay_turn_end` from the relay) and a cold-cache status probe (`status_probe`) notify observers once (S1). The inferred stop and disconnect outcomes (shared `_inferred_turn`) are reported only for a response with no recorded outcome; otherwise the edge carries neither an outcome nor a turn id (S1). The relay passes the runner's `turn_outcome` and `turn_response_id` on every relayed status edge to observers; unknown values and old runners give none (S43). |
| `omnigent/server/routes/auth.py` | S92, S95 | coral-specific | The CLI login consent page now says "A Coral client", "this Coral server" and "from Coral", and its title suffix is "— Coral"; the upgrade notice, the omnigent login text and the server messages stay as they were (S92) Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/device_auth.py` | S92 | coral-specific | The device-grant consent page now says "this Coral server" and its title is "Authorize access — Coral"; env var names, protocol headers and client ids stay as they were (S92) |
| `omnigent/server/routes/host_tunnel.py` | S72, S40 | upstreamable, coral-specific | The create-worktree result relay passes `head_commit` on to the waiting proxy (S72). The tunnel relays a `host.workspace_op_result`'s six fields to its waiting request and logs a late result at debug (S40). |
| `omnigent/server/routes/sessions/routes_events.py` | S42, S1 | coral-specific | `EngineEventContext` joins the request-free sender types: it is authorized as its own `user_id` and its message is never saved behind managed startup. It may send only `message`, `interrupt` and `stop_session` (others `FORBIDDEN`), and a message whose first text starts with `!` or `/` is refused (`INVALID_INPUT`) before any dispatch. A host refusal in the host-bound relaunch ladder raises `RUNNER_UNAVAILABLE` for it instead of recording a failed turn and reporting `queued`; a side chat's source-relaunch refusal is unchanged (S42). Deleting a session forgets its and its descendants' recorded turn outcomes (S1). |
| `omnigent/server/routes/sessions/routes_permissions.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/server_plugins.py` | S32 | upstream-extension | Added. Defines `ServerServices`, `ServerPluginRegistration`, `load_server_plugins`, and `enter_lifespan_hooks` (S32). |
| `omnigent/server/session_live_state.py` | S1 | coral-specific | Adds `SessionStatusEdge` (runner-supplied ids, codes and text bounded on construction), `TURN_OUTCOMES`, `turn_fields` (a response id only with a known outcome) and a thread-safe in-process status-edge observer registry (`register_status_edge_observer`, which warns on a replacement by name, and `notify_status_edge`, which isolates each observer and logs one traceback per failing observer name); observers match on `(workspace_id, session_id)`; every notified edge with an outcome and a response id is recorded per `(workspace_id, session_id)` (last 8 ids per session, at most 4,096 sessions, least recently reported first out), read by `turn_outcome_reported` and dropped by `forget_turn_outcomes` (S1). |
| `omnigent/server/startup_inputs.py` | S42 | coral-specific | Adds `EngineEventContext(app, user_id)`, an in-process engine sender whose headers are always empty (callers cannot pass any), and the `SessionEventDispatch` protocol for the shared event handler (S42). |
| `omnigent/server/static/api_only_landing.html` | S92 | coral-specific | On the API-only landing page the title and heading name Coral, and the Details link points to the coral-hq/coral README; the OMNIGENT_SKIP_WEB_UI mentions and the uv cache clean omnigent command stay as they were (S92) |
| `omnigent/session_import/local.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/__init__.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/_omnigent_compat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/omnigent.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/stores/scheduled_task_store/sqlalchemy_store.py` | S58 | upstream-extension | Delegates _cursor_after to shared keyset_after helper (S58). |
| `omnigent/telemetry/client.py` | S98 | coral-specific | Telemetry is always disabled: Coral sends no usage telemetry to Omnigent's service. |
| `omnigent/tools/builtins/async_inbox.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/browser.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/spawn.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/ui.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/manager.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/util/session_lifecycle.py` | S51 | upstreamable | Adds `PARENT_WAKE_LABEL_KEY` (`omnigent.parent_wake`) and `PARENT_WAKE_OFF_VALUE` (`off`) beside the closed-label constants (S51). |
| `omnigent/util/tmux_compat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/workspace_fs.py` | S71 | upstreamable | `WorkspaceReader` takes a keyword-only `start_registry` (default `True`); with `False` it does not start the change registry's background git probe. File reads and diffs open files non-blocking and refuse FIFOs, devices and other non-regular files (S71). |
| `openapi.json` | S95 | coral-specific | Regenerated: the title and API descriptions follow the S95 brand transform. |
| `pnpm-lock.yaml` | S83 | coral-specific | Locks `@fontsource-variable/newsreader` 5.3.0 (S83). |
| `pyproject.toml` | S29, S39b, S39c, S40b | coral-specific | Points `coral` at `coral.cli:main`, includes `coral*` and Coral package data (S29); adds `"coral"` to isort `known-first-party` (S39b) and `[tool.coverage.run].source` (S39c). Declares Coral's `omnigent.host_workspace_ops` entry point, `coral = "coral.omni.host.ops:workspace_op_handlers"` (S40b). |
| `pyrefly.toml` | S39e | coral-specific | Includes `coral/**/*.py` and `coral/**/*.pyi` in typechecking (S39e). |
| `tests/browser_ui/chat/test_color_theme.py` | S82 | coral-specific | The default palette is labelled "Coral" with Coral's selection washes (S82). |
| `tests/browser_ui/chat/test_status_indicators.py` | S79 | coral-specific | The working indicator's Coral mark holds still while its opacity pulses, replacing the Otto blink check (S79). |
| `tests/cli/test_backend.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_chat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_cli.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_cli_diagnostics.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_crash_handler.py` | S96, S95 | coral-specific | Renders the crash screen with the `coral` app name the CLI now passes. Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_import.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/cli/test_login_databricks.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/conftest.py` | S31 | upstream-extension | Preserves alembic_version and coral_alembic_version during test table truncation across Postgres, MySQL, and CockroachDB (S31). |
| `tests/db/test_crdb_core.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/dev/lint/test_custom_lint.py` | S39 | coral-specific | Asserts `coral-import-boundary` is registered last in `custom_lint.RULES` (S39). |
| `tests/e2e/integrations/deploy/gensee/test_managed_lifecycle.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/integrations/deploy/kubernetes/e2e_managed_host_config.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/omnigent/_snapshot.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/omnigent/conftest.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/omnigent/test_host_no_open.py` | S38 | coral-specific | `--open-in-desktop` opens a `coral://` link (S38). |
| `tests/e2e/omnigent/test_per_harness_antigravity.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/omnigent/test_per_harness_openai_agents_sdk.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/omnigent/test_pi_managed_extensions_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/resilience/lab/tls.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_claude_question_message_repl_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_codex_cold_resume_compaction_image_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_codex_native_child_visibility_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_codex_rotated_bridge_relaunch_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_comment_tools_claude_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_conversation_append_race_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_cursor_native_cli_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_cursor_native_forwarder_fd_exhaustion_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_cursor_native_hooks_merge_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_host_claude_native_fork_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_host_cross_family_fork_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_kimi_native_steering_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_native_resume_provider_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_pi_native_smart_routing.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_polly_codex_subscription_login_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_pytest_process_leak_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_run_invalid_proxy_env_crash.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_run_mcp_url_env_expansion_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_runner_tunnel_mid_turn_reconnect_grace_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e/test_web_search_claude_sdk_bare_model.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/agents/test_subagent_activity.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/branding/test_branding.py` | S79, S80 | coral-specific | The default hero heading is "Direct the run…" (S79) and the default sidebar link reads "Coral" (S80). |
| `tests/e2e_ui/browser/test_browser_priority_guidance.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/chat/test_codex_native_ambient_bedrock.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/chat/test_codex_working_indicator_restart.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/chat/test_failure_error_card.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/collaboration/test_permissions_modal.py` | S89 | coral-specific | The QR code locator now matches the aria-label 'QR code to open this session in the Coral app' (S89). |
| `tests/e2e_ui/collaboration/test_sharing_mode_off.py` | S89 | coral-specific | _OFF_REASON, which mirrors AppShell's shareDisabledReason, now expects 'Sharing has been disabled for this Coral server.'; the server's 403 text is unchanged (S89). |
| `tests/e2e_ui/desktop/test_about_dialog.py` | S87 | coral-specific | Expects the Coral heading, the attribution and the Licence and Notices buttons (S87). |
| `tests/e2e_ui/sessions/test_settings_export_import.py` | S89 | coral-specific | Settings import e2e test expects the 'valid Coral settings' alert text (S89). |
| `tests/e2e_ui/sessions/test_sidebar_view_options.py` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `tests/e2e_ui/start_session/test_unpinned_codex_default_model.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/e2e_ui/visual/test_landing_snapshot.py` | S79 | coral-specific | Docstring names the new hero (S79); CI regenerates the baseline. |
| `tests/extensions/test_registry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/driver.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/full_server_driver.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/manifest.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/native_tui_driver.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/probes/omnigent_mcp.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/test_native_tui_driver.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harness_bench/test_omnigent_mcp.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/antigravity_native/test_antigravity_native_bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/claude_native/forwarder/test_session_lifecycle.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/claude_native/forwarder/test_settlement.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/claude_native/test_claude_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/claude_native/test_claude_native_bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/claude_native/test_claude_native_hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/app_server/test_policy_hooks.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/session/test_approvals.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/session/test_resume_rollouts.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/session/test_subagents.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/test_codex_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/harnesses/codex_native/test_codex_native_hook.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/helpers/ui_url_safety.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/host/test_cli_host.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/host/test_connect.py` | S71, S72 | upstreamable | A cancelled worktree create/remove/list or fs request frame keeps the orphan reaper paused until its worker exits, and the host's fs reader never starts the change registry (S71). The create-worktree handler's reply carries `head_commit`, and the list handler's entries carry `locked` (S72). |
| `tests/host/test_frames.py` | S72, S40 | upstreamable, coral-specific | The create-worktree result round trip keeps `head_commit`; a result without it decodes to `None` and a non-string is rejected (S72). `HOST_CAPABILITIES` has `workspace_ops:1`; workspace-op requests and results round-trip exactly with their documented wire keys, a result without `permanent` reads as retryable, and 27 malformed frames raise `ValueError`, including a timeout too large for a float, an ok result without a payload and a failed one without a code (S40). |
| `tests/host/test_git_worktree.py` | S72 | upstreamable | `head_commit` equals the worktree's `rev-parse HEAD` for a new branch from a base, the existing-branch recreate and both pinned paths (with no extra git call on the pinned checkout); an unreadable HEAD (any error) gives `None` and keeps the worktree; a missing path, a plain directory and a file are rejected; a locked worktree, with or without a reason, lists as `locked` and others do not (S72). |
| `tests/host/test_local_server.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/host/test_orphan_reaper.py` | S71 | upstreamable | Fs request, fs write, skills, skill-content and credential-detection frames dispatched while a sweep runs keep the reaper paused, lose no child, and report the child's exit code 42 (S71). |
| `tests/host/test_workspace_ops.py` | S40, S40b | coral-specific | Added. A reaper sweep during a workspace op leaves the child's exit code 42 to the handler; raw frames reach patched handlers through the host's dispatch under the guard, a raising handler and an unknown op are still answered, and a third concurrent op waits for a slot without a thread or a paused reaper; the dispatcher's request and deadline, permanent refusals of bad roots and op keys, typed and ill-typed handler errors, message trimming, type-only exceptions, the catch-all, payload refusals, the 8 MiB result cap, one-pass serialisation in the worker and both root flavours (S40). Broken entry points are skipped with a warning, an empty contribution is silent, an op offered by two packages is served by neither, a failed plugin is named in `unknown_op`, installed handlers load once, and importing the host loads none (S40b). |
| `tests/inner/test_claude_sdk_executor.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/inner/test_terminal.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/inner/test_ui.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/onboarding/test_harness_install.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/onboarding/test_setup_flow.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/repl/test_repl.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/repl/test_report_command.py` | S96 | coral-specific | Expects the `/bug` URL on coral-hq/coral. |
| `tests/runner/test_app_sessions_native_terminals_autocreate.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_app_sessions_native_terminals_runtime.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_app_sessions_native_workflow_init.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_app_sessions_native_workflow_messages.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_browser_tool_dispatch.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_comment_relay.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_native_terminal_start_error_payload.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runner/test_runner_dispatch.py` | S43 | coral-specific | Interrupted, cancelled, completed, waiting and failed turn ends name their response and outcome; an interrupt that cancels a streaming turn reports it cancelled, with input buffered too (one outcome for the interrupted response); a buffered continuation after an interrupted, completed or failed turn reports the turn once and its own end names its own response; both drain exits with the queue gone take the carried outcome; delete drops it; the init failure reports `failed` with no response; the desync failure names the response it ended (S43). |
| `tests/runner/test_runner_entry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runtime/harnesses/test_executor_adapter.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runtime/test_filesystem_registry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runtime/test_subagent_block_notifier.py` | S51 | upstreamable | No label, `on`, `OFF` and ` off` wake the parent and only an exact `off` does not; an `off` block stays debounced, its resolve sends no notice, clears it and leaves no resolve signal behind, and "no wake" is asserted only after the handler has returned (S51). |
| `tests/scripts/test_dependency_ci.py` | S39d | coral-specific | Asserts the `coral` matrix group collects `tests/coral` and `misc` ignores it (S39d). |
| `tests/scripts/test_security_gate.py` | S99 | coral-specific | Expects the gate and scan to fetch their trust rules from the default branch. |
| `tests/server/integration/test_engine_event_dispatch.py` | S41, S42 | coral-specific | Added. The event handler is kept with and without managed sandboxes (S41); an engine context's brief persists under its stable id and passes the closed check and input policy, interrupt and stop reach the runner, it acts as its own user with empty headers, other event types (`approval` among them) and briefs starting `!ls`, `/side x` or `/login` are refused, its message skips the managed startup queue, and a host refusal in the relaunch ladder raises `RUNNER_UNAVAILABLE` (S42). |
| `tests/server/integration/test_hosts_worktrees.py` | S72 | upstreamable | The mock host also answers create-worktree frames (a create with no registered reply fails at once), and the real tunnel relay delivers `head_commit` to `create_worktree_on_host` (S72). |
| `tests/server/integration/test_kiro_permission_delivery.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_lifespan.py` | S98 | coral-specific | Expects the server never to start the telemetry client, in CI or not. |
| `tests/server/integration/test_oidc_cli_ticket_hijack_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_session_create_harness_readiness.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_session_host_launch.py` | S51 | upstreamable | Topology probes for a run anchor with no host: each host child launches, keeps and stops its own runner and outlives the anchor's stop, a replacement child launches its own while its sibling keeps its runner, a host-bound anchor's child rides its runner instead, and of two blocked children only the one not labelled `omnigent.parent_wake: off` wakes the anchor after the 120 s grace (S51). |
| `tests/server/integration/test_sessions_compact.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/routes/test_disconnect_outcome_recovery.py` | S1 | coral-specific | The offline sweep's failure reports `failed` with the dropped turn's id (none without one), the runner-recovered status reports one idle edge, and none when the session is not failed or keeps a genuine failure; a turn the runner already reported keeps its one outcome (S1). |
| `tests/server/routes/test_host_workspace_ops.py` | S40 | coral-specific | Added. A host without the token, a frame the host would drop or refuse, and a send without a host-owner scope naming the connection are each refused before any frame; deregister and replace fail a pending op at once; a cancelled request leaves no pending entry; an unanswered op times out after its timeout plus the grace; through the real host tunnel a result resolves its request with all six fields, the host's error text is cut and a malformed code reads as `handler_failed`, and late, unknown, malformed and duplicate results are dropped without closing the tunnel (S40). |
| `tests/server/routes/test_host_worktree.py` | S72 | upstreamable | The create proxy keeps a SHA-1 or SHA-256 `head_commit`; an older host's result without it, and a non-hex, abbreviated, uppercase, too-long or non-string value, give `None` (S72). |
| `tests/server/routes/test_intentional_runner_stop.py` | S1 | coral-specific | Stop, archive, offline-sweep and relay-transport idle edges report a running turn as `cancelled` with its response id and a waiting one with no outcome; only the archived session is `archive_idle`; a settlement followed by the relay's drop reports the turn cancelled once; a stop while a continuation still names the turn the runner reported completed adds no outcome (S1). |
| `tests/server/routes/test_session_resources.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/routes/test_sessions_runner_relay.py` | S1, S43 | coral-specific | A stop of a session with no turn in flight reports its idle edge without a turn outcome, and a runner drop after a reported `waiting` or continuation turn end adds no second outcome (S1). Relayed status edges hand the runner's turn outcome and response id to observers, never to the stream payload; an id without a known outcome is dropped (S43). |
| `tests/server/routes/test_sessions_snapshot.py` | S1 | coral-specific | A cold-cache status probe reports one `status_probe` edge; a warm read, a probe that finds the cache filled, or an unrecognized probed status reports none (S1). |
| `tests/server/routes/test_sessions_upload_limits.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_admin_list.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_app.py` | S32 | upstream-extension | Adds server-plugin loading, failure abort, lifespan ordering, bundle policy registration, and `/v1/coral/info` gate tests (S32). |
| `tests/server/test_oidc_cli_ticket.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_runner_session_init.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_session_live_state.py` | S1 | coral-specific | The observer registry (replacement warning, identity-checked idempotent unregister, a raising observer that runs first and is logged once, re-entrancy mid-notify), edge bounds, `turn_fields` (no id without an outcome), one edge per `_publish_status` after the stream with every field, a worker-thread publish, the origin at the four sites, the reported-outcome record's per-session and session bounds and workspace keys, and its drop on session delete (S1). |
| `tests/test_codex_effort_terminal_composer_mirror.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_conversation_browser.py` | S38 | coral-specific | Expects `coral://` deep links; fake openers key on `coral:` (S38). |
| `tests/test_devin_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_harness_diagnostics.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_kimi_native_forwarder.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_kiro_native.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_native_terminal.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_native_wrappers_shared.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_opencode_native_bridge.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_telemetry.py` | S98 | coral-specific | Expects telemetry to stay disabled with no opt-out set and with `telemetry: true` in config. |
| `tests/test_ui_url_safety.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_uninstall_cli.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/test_workspace_fs.py` | S71 | upstreamable | `WorkspaceReader` starts the change registry by default and with `start_registry=True`, and not with `False`; a FIFO is refused at once by file reads and diffs while regular files read as before (S71). |
| `tests/tools/test_mcp.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `web/android/app/src/androidTest/java/ai/omnigent/android/ScreenshotTest.kt` | S88 | coral-specific | The connect field hint names a Coral server (S88). |
| `web/android/app/src/main/java/ai/omnigent/android/BlobSaver.kt` | S88 | coral-specific | Saved files default to a `coral-` name (S88). |
| `web/android/app/src/main/java/ai/omnigent/android/NativeNotificationManager.kt` | S88 | coral-specific | Notifications use the Coral silhouette (S88). |
| `web/android/app/src/main/res/drawable-hdpi/coral_launcher_foreground.png` | S88 | coral-specific | Added. Adaptive launcher foreground at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-hdpi/coral_launcher_monochrome.png` | S88 | coral-specific | Added. Themed (monochrome) launcher layer at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-hdpi/coral_logo.png` | S88 | coral-specific | Added. Connect-screen logo at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-hdpi/coral_notification.png` | S88 | coral-specific | Added. Notification small icon (white mask) at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-mdpi/coral_launcher_foreground.png` | S88 | coral-specific | Added. Adaptive launcher foreground at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-mdpi/coral_launcher_monochrome.png` | S88 | coral-specific | Added. Themed (monochrome) launcher layer at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-mdpi/coral_logo.png` | S88 | coral-specific | Added. Connect-screen logo at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-mdpi/coral_notification.png` | S88 | coral-specific | Added. Notification small icon (white mask) at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xhdpi/coral_launcher_foreground.png` | S88 | coral-specific | Added. Adaptive launcher foreground at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xhdpi/coral_launcher_monochrome.png` | S88 | coral-specific | Added. Themed (monochrome) launcher layer at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xhdpi/coral_logo.png` | S88 | coral-specific | Added. Connect-screen logo at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xhdpi/coral_notification.png` | S88 | coral-specific | Added. Notification small icon (white mask) at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxhdpi/coral_launcher_foreground.png` | S88 | coral-specific | Added. Adaptive launcher foreground at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxhdpi/coral_launcher_monochrome.png` | S88 | coral-specific | Added. Themed (monochrome) launcher layer at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxhdpi/coral_logo.png` | S88 | coral-specific | Added. Connect-screen logo at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxhdpi/coral_notification.png` | S88 | coral-specific | Added. Notification small icon (white mask) at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxxhdpi/coral_launcher_foreground.png` | S88 | coral-specific | Added. Adaptive launcher foreground at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxxhdpi/coral_launcher_monochrome.png` | S88 | coral-specific | Added. Themed (monochrome) launcher layer at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxxhdpi/coral_logo.png` | S88 | coral-specific | Added. Connect-screen logo at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/drawable-xxxhdpi/coral_notification.png` | S88 | coral-specific | Added. Notification small icon (white mask) at one density. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/android/app/src/main/res/layout/activity_connect.xml` | S88 | coral-specific | The connect screen shows the Coral mark (S88). |
| `web/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml` | S88 | coral-specific | Adaptive launcher icon uses the Coral drawables on cream (S88). |
| `web/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher_round.xml` | S88 | coral-specific | Adaptive launcher icon uses the Coral drawables on cream (S88). |
| `web/android/app/src/main/res/values/coral_colors.xml` | S88 | coral-specific | Added. Cream launcher background colour (S88). |
| `web/android/app/src/main/res/values/strings.xml` | S88 | coral-specific | User-visible app strings name Coral (S88). |
| `web/electron/about/index.html` | S87, S88 | coral-specific | Coral title and headings, the Apache-2.0 attribution, and Licence and Notices buttons (S87); the fallback icon is the Coral icon (S88). |
| `web/electron/about/index.js` | S87 | coral-specific | Coral headings and the Licence and Notices button handlers (S87). |
| `web/electron/connection-loading/index.html` | S87 | coral-specific | "Opening Coral…" (S87). |
| `web/electron/dev-app-update.yml` | S87 | coral-specific | Dev builds read Coral's feed with a `coral-desktop-updater-dev` cache (S87). |
| `web/electron/dmg/coral-background.tiff` | S87 | coral-specific | Added. Coral DMG background: cream ground with Clay washes and an install arrow (S87). |
| `web/electron/e2e/desktopHarness.js` | S87 | coral-specific | Seeds the "Coral Dev" profile folder (S87). |
| `web/electron/e2e/desktop_arca_onboarding.e2e.js` | S89b | coral-specific | Queries follow the Coral onboarding copy (S89b). |
| `web/electron/e2e/desktop_connect.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_cookie_isolation.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_navigation_policy.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_oidc_browser_sign_in.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_recording_shows_views.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_saved_server_unresponsive.e2e.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/e2e/desktop_session_expiry_browser_view.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/e2e/desktop_update_window.e2e.js` | S79 | coral-specific | The default hero heading is "Direct the run…" (S79). |
| `web/electron/icons/Assets.car` | S88 | coral-specific | The macOS 26 dynamic icon, compiled with Xcode's actool from the Coral `AppIcon.icon` bundle (the Coral logo on cream). |
| `web/electron/icons/coral-icon.icns` | S88 | coral-specific | Added. Desktop app icon: the Coral logo on the cream plate. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-icon.ico` | S88 | coral-specific | Added. Desktop app icon: the Coral logo on the cream plate. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-icon.png` | S88 | coral-specific | Added. Desktop app icon: the Coral logo on the cream plate. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/128x128.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/16x16.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/24x24.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/256x256.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/32x32.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/48x48.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/512x512.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/icons/coral-linux/64x64.png` | S88 | coral-specific | Added. Linux launcher icon at one size (`linux.icon` names the folder). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/electron/package.json` | S87, S38, S88 | coral-specific | Coral product name, description, homepage, repository, author, app id and dev overrides, Coral update feed, copyright with the Databricks credit, unsigned mac identity, microphone copy, maintainer, DMG background and LICENSE/NOTICE/MODIFICATIONS.md/OFL texts in `legal/` (S87); registers the `coral` session-link scheme (S38); Coral icons for macOS, Windows and Linux (S88). npm name unchanged. |
| `web/electron/return-banner/index.html` | S87 | coral-specific | The return banner names Coral (S87). |
| `web/electron/setup/index.html` | S89b | coral-specific | "Coral — Connect": Coral tokens and washes, the Coral mark beside a serif "Coral", the accent rail, and "Run a Coral server…" (S89b). |
| `web/electron/src/about_preload.js` | S87 | coral-specific | Exposes `openLegalFile` to the About page (S87). |
| `web/electron/src/about_window.js` | S87 | coral-specific | Coral window title, a taller window, and an IPC handler that opens the shipped LICENSE, NOTICE or MODIFICATIONS.md (S87). |
| `web/electron/src/brand.js` | S87 | coral-specific | Added. Coral's desktop identity: product names, app ids, `coral` scheme, CLI names, install command, update feed and contact links (S87). |
| `web/electron/src/browserIpc.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/databricks-oauth.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/deepLink.js` | S38 | coral-specific | Accepts only `coral://` session links (`brand.js` `URL_SCHEME`) (S38). |
| `web/electron/src/desktop_updater.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/dev_preferences.js` | S87 | coral-specific | Dev defaults domain is `DEV_APP_ID` (S87). |
| `web/electron/src/main.js` | S87, S38, S88 | coral-specific | Product name, app name, dev userData folder and Windows AppUserModelId come from `brand.js`; the About window gets the licence-file location (S87); argv scans and protocol registration use `URL_SCHEME` (S38); the runtime icon is `coral-icon.png` (S88). |
| `web/electron/src/oidc-credentials.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/omnigent_cli.js` | S87 | coral-specific | CLI names (adding `coral`) and the install command come from `brand.js`; the version check accepts `coral` (S87). |
| `web/electron/src/quitConfirmation.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/ssh_connect.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/src/ssh_connect_window.js` | S87 | coral-specific | Shell copy names Coral via `brand.js` `PRODUCT_NAME` (S87). |
| `web/electron/ssh-connect/console.js` | S87 | coral-specific | The SSH console names Coral (S87). |
| `web/electron/test/about_page.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/test/about_window.test.js` | S87 | coral-specific | Covers the licence-file handler and the attribution markup, and expects Coral headings (S87). |
| `web/electron/test/brand.test.js` | S87, S38 | coral-specific | Added. Refuses Omnigent or Databricks publisher identity in package.json, checks it mirrors `brand.js`, and checks the legal files ship (S87) and that only `coral` is registered (S38). |
| `web/electron/test/chromeCookieImportPrompt.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/test/databricks-oauth.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/test/deepLink.test.js` | S38 | coral-specific | Fixtures use `coral://`; `omnigent://` is rejected (S38). |
| `web/electron/test/desktop_updater.test.js` | S87 | coral-specific | Expects Coral consent copy and pins the dev updater cache name (S87). |
| `web/electron/test/main.test.js` | S87, S38 | coral-specific | Assertions follow the shell copy, which names Coral (S87), and the `coral://` scan and registration (S38). |
| `web/electron/test/omnigent_cli.test.js` | S87 | coral-specific | Covers `coral` CLI detection (S87). |
| `web/electron/test/quitConfirmation.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/test/ssh_connect.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/electron/test/update-main.test.js` | S87 | coral-specific | Assertions follow the shell copy, which names Coral (S87). |
| `web/index.html` | S89 | coral-specific | Coral favicon, apple-touch icon, theme colour and tab title, and a cream "Loading Coral…" boot screen (S89). |
| `web/ios/Omnigent.xcodeproj/project.pbxproj` | S88 | coral-specific | `APP_DISPLAY_NAME` is Coral and the app icon source is `platform-assets/coral/AppIcon.icon` (S88). |
| `web/ios/Omnigent/AppRootView.swift` | S38 | coral-specific | The deep-link consent alert names Coral (S38). |
| `web/ios/Omnigent/Assets.xcassets/CoralLogo.imageset/Contents.json` | S88 | coral-specific | Added. Imageset holding the Coral logo at 1x, 2x and 3x for the iOS connect screen. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogo.imageset/coral-logo.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogo). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogo.imageset/coral-logo@2x.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogo). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogo.imageset/coral-logo@3x.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogo). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogoReverse.imageset/Contents.json` | S88 | coral-specific | Added. Imageset holding the Coral logo at 1x, 2x and 3x for the iOS connect screen. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogoReverse.imageset/coral-logo.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogoReverse). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogoReverse.imageset/coral-logo@2x.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogoReverse). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/Assets.xcassets/CoralLogoReverse.imageset/coral-logo@3x.png` | S88 | coral-specific | Added. The Coral logo for the iOS connect screen (CoralLogoReverse). Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/ios/Omnigent/ConnectView.swift` | S88, S89b | coral-specific | The connect screen shows the Coral mark, names a Coral server and labels About as Coral (S88); Website and Privacy Policy open Coral's repository and PRIVACY.md, Docs stays upstream (S89b). |
| `web/ios/Omnigent/DeepLink.swift` | S38 | coral-specific | Accepts only `coral://` session links (S38). |
| `web/ios/Omnigent/Info-Debug.plist` | S38, S88 | coral-specific | Camera, microphone and speech permission prompts name Coral (S88); the session-link URL scheme is `coral` (S38). |
| `web/ios/Omnigent/Info-Release.plist` | S38, S88 | coral-specific | Camera, microphone and speech permission prompts name Coral (S88); the session-link URL scheme is `coral` (S38). |
| `web/ios/OmnigentTests/DeepLinkTests.swift` | S38 | coral-specific | Fixtures use `coral://`; `omnigent://` is rejected (S38). |
| `web/ios/OmnigentUITests/OmnigentUITests.swift` | S38 | coral-specific | Deep links use `coral://` and the consent alert names Coral (S38). |
| `web/ios/OmnigentUITests/RedirectConsentUITests.swift` | S38 | coral-specific | Deep links use `coral://` and the consent alert names Coral (S38). |
| `web/package.json` | S83 | coral-specific | Adds the `@fontsource-variable/newsreader` dependency (S83). |
| `web/platform-assets/coral/AppIcon.icon/Assets/Coral Logo.png` | S88 | coral-specific | Added. The Coral logo layer of the iOS Icon Composer bundle. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/platform-assets/coral/AppIcon.icon/icon.json` | S88 | coral-specific | Added. Coral's Icon Composer bundle: a cream fill and the Coral logo layer. |
| `web/platform-assets/logos/coral-logo.png` | S88 | coral-specific | Added. The Coral logo shown on the Electron setup page. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/public/coral-apple-touch-icon.png` | S89 | coral-specific | Added. The apple-touch icon: the Coral logo on the cream plate. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/public/coral-favicon.png` | S89 | coral-specific | Added. The web UI favicon. Generated from the Coral logo by `.coral/tools/brand_assets.py`. |
| `web/public/licenses/geist-mono-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Geist Mono (`@fontsource-variable/geist-mono`), shipped with the web UI. |
| `web/public/licenses/newsreader-OFL-1.1.txt` | S77 | coral-specific | Added. Verbatim SIL OFL 1.1 text of Newsreader (`@fontsource-variable/newsreader`), shipped with the web UI. |
| `web/server-selector-v2.html` | S89b | coral-specific | Window title "Coral — Connect" (S89b). |
| `web/src/components/BrandLogo.test.tsx` | S79 | coral-specific | Fallback cases expect the Coral mark (S79). |
| `web/src/components/BrandLogo.tsx` | S79 | coral-specific | The no-logo and failed-logo fallback is `CoralMark` instead of the Otto mascot (S79). |
| `web/src/components/BrowserPane/BrowserPane.test.tsx` | S89 | coral-specific | The cookie-import dialog assertion now expects "Other sites' cookies stay out of Coral entirely." (S89). |
| `web/src/components/BrowserPane/BrowserPane.tsx` | S89 | coral-specific | The Chrome cookie-import dialog names the app through useAppName() ("disappears when Coral quits", "stay out of Coral entirely") instead of Omnigent (S89). |
| `web/src/components/KeyboardShortcutsDialog.test.tsx` | S89 | coral-specific | The desktop-commands test now expects the "Quit Coral" shortcut row instead of "Quit Omnigent" (S89). |
| `web/src/components/KeyboardShortcutsDialog.tsx` | S89 | coral-specific | The desktop command list is now built per render by desktopCommandShortcuts(appName), so the Quit row reads `Quit ${useAppName()}` (Coral by default) instead of the fixed "Quit Omnigent" (S89). |
| `web/src/components/PageLoading.tsx` | S89 | coral-specific | When no label prop is passed, PageLoading now shows `Loading ${useAppName()}…` (Coral by default) instead of "Loading Omnigent…" (S89). |
| `web/src/components/PermissionsModal.designs.stories.tsx` | S89, S38 | coral-specific | The sample QR link uses `coral://` (S38) and the sample sharing copy names Coral (S89). |
| `web/src/components/PermissionsModal.test.tsx` | S89, S38 | coral-specific | Expects `coral://` QR links (S38). Test assertions on the sharing-off and server-mode notices now expect 'Coral server' (S89). |
| `web/src/components/PermissionsModal.tsx` | S89, S38 | coral-specific | The share QR encodes a `coral://` link from `web/src/brand/urlScheme.ts` (S38). The share modal's sharing-off notice, server-mode notices, blocked-workspace notice, and the QR dialog's description and aria-label now name the app through useAppName() (default Coral) instead of Omnigent (S89). |
| `web/src/components/SlashCommandMenu.tsx` | S89 | coral-specific | The skill wand carries a `slash-skill-icon` hook that `coral.css` tints clay in the default palette; other palettes keep pink (S89). |
| `web/src/components/UpdateBanner.test.tsx` | S89 | coral-specific | The update banner tests now expect "Coral Desktop" copy for the available, downloading and ready-to-install states (S89). |
| `web/src/components/UpdateBanner.tsx` | S89 | coral-specific | The update banner's available, downloading and ready-to-install lines now say "{appName} Desktop" via useAppName() (Coral by default) instead of "Omnigent Desktop" (S89). |
| `web/src/components/blocks/ApprovalCard.test.tsx` | S89 | coral-specific | The Antigravity always-allow title assertion now expects "for this Coral session" (S89). |
| `web/src/components/blocks/ApprovalCard.tsx` | S89 | coral-specific | The Antigravity always-allow button title and the hint under it name the app's session through useAppName() ("this Coral session") instead of "this Omnigent session" (S89). |
| `web/src/components/onboarding/AnimatedOmnigentPanel.tsx` | S89 | coral-specific | Shows the Coral mark; its `alt` and the card's `aria-label` follow `useAppName()` (S89). |
| `web/src/components/onboarding/BlobGraphic.tsx` | S89 | coral-specific | Blob colours become forest, mustard and terracotta (S89). |
| `web/src/components/onboarding/ImportContextModal.tsx` | S89 | coral-specific | Shows the Coral mark instead of the Omnigent starfish (S89). |
| `web/src/components/scheduled/CreateScheduledTaskDialog.test.tsx` | S89 | coral-specific | Updated the expected trigger attribution note ("Sent with Coral") and link-back prompt text ("Coral session:") in the trigger dialog tests (S89). |
| `web/src/components/scheduled/triggerTemplates.test.ts` | S89 | coral-specific | Updated the expected attribution and link-back text to say Coral, and added a test for each source showing that a rendered prompt with its attribution swapped back to "Sent with Omnigent" still splits into the same userPrompt and round-trips through combineTriggerPrompt (S89). |
| `web/src/components/scheduled/triggerTemplates.ts` | S89 | coral-specific | Trigger templates now use the Jira label placeholder "coral", the link-back text "Coral session:" and OMNIGENT_ATTRIBUTION "Sent with Coral"; splitTriggerPrompt and combineTriggerPrompt also accept the legacy posting instructions built from "Sent with Omnigent", so saved prompts still split and round-trip byte for byte (S89). |
| `web/src/index.css` | S83 | coral-specific | Imports Newsreader and `./brand/coral.css`, and adds `--font-display` (S83). |
| `web/src/index.css.test.ts` | S83 | coral-specific | Asserts the Newsreader import and `--font-display`, and that `--font-heading` stays sans (S83). |
| `web/src/lib/branding.ts` | S79 | coral-specific | Built-in defaults become "Coral" and "Direct the run…"; operator branding still overrides them (S79). |
| `web/src/lib/customTheme.test.ts` | S82 | coral-specific | Rebaselines the default palette's selection tint to Coral's washes (S82). |
| `web/src/lib/harnessSetup.ts` | S89 | coral-specific | resolveSetupSteps takes an optional appName (default DEFAULT_APP_NAME), and the synthesized tmux step's detail uses it instead of hard-coded Omnigent (S89). |
| `web/src/lib/settingsPortability.ts` | S89 | coral-specific | Settings export now downloads as coral-settings.json and the invalid-file import error names DEFAULT_APP_NAME; import checks only the .json extension and content shape, so omnigent-settings.json exports still load (S89). |
| `web/src/lib/terminalClipboardPreferences.test.ts` | S89 | coral-specific | Clipboard-preference import test expects the 'valid Coral settings' error (S89). |
| `web/src/lib/themePalette.test.ts` | S82 | coral-specific | Replaces the Omnigent pink/magenta pins with Coral rules and adds stored-`omni`, storage-failure and readable-text checks (S82). |
| `web/src/lib/themePalette.ts` | S82 | coral-specific | The default `omni` palette carries Coral's Clay Score tokens and the label "Coral"; its id and `DEFAULT_PALETTE` are unchanged (S82). |
| `web/src/pages/RegisterPage.tsx` | S89 | coral-specific | "this Omnigent server" follows `useAppName()` (S89). |
| `web/src/pages/SettingsPage.test.tsx` | S89 | coral-specific | SettingsPage tests expect the Coral General/Appearance descriptions and the 'Show Coral from anywhere' switch (S89). |
| `web/src/pages/SettingsPage.tsx` | S89 | coral-specific | Settings Appearance, Git and General descriptions, the import dialog copy and the Updates 'Check when ... starts' label now use useAppName(), and the custom-theme 'Based on' fallback reads Coral (S89). |
| `web/src/pages/onboarding/AuthCardShell.tsx` | S89 | coral-specific | Shows the Coral mark with `alt` from `useAppName()` (S89). |
| `web/src/pages/onboarding/JoinTeamStep.tsx` | S89 | coral-specific | "their Omnigent server" follows `useAppName()` (S89). |
| `web/src/pages/onboarding/LandingFooter.tsx` | S89b | coral-specific | GitHub points at Coral's repository, the iOS App, Android App and Discord buttons are removed, and the maintained-by line reads "Built on Omnigent" (S89b). |
| `web/src/pages/onboarding/LandingStep.tsx` | S89b | coral-specific | Onboarding copy names Coral (`DEFAULT_APP_NAME`) (S89b). |
| `web/src/pages/onboarding/LocalIntroStep.tsx` | S89b | coral-specific | Onboarding copy names Coral (`DEFAULT_APP_NAME`) (S89b). |
| `web/src/pages/onboarding/ServerSelectStep.render.test.tsx` | S89b | coral-specific | Queries follow the Coral onboarding copy (S89b). |
| `web/src/pages/onboarding/ServerSelectStep.tsx` | S89b | coral-specific | Onboarding copy names Coral (`DEFAULT_APP_NAME`); "Create server" opens Coral's repository (S89b). |
| `web/src/pages/onboarding/ServerSelectorV2.test.tsx` | S89b | coral-specific | Queries follow the Coral onboarding copy (S89b). |
| `web/src/pages/onboarding/ServerSelectorV2.tsx` | S89b | coral-specific | Onboarding copy names Coral (`DEFAULT_APP_NAME`) (S89b). |
| `web/src/pages/onboarding/SetupTerminalStep.tsx` | S89b | coral-specific | Onboarding copy names Coral (`DEFAULT_APP_NAME`) (S89b). |
| `web/src/pages/onboarding/primitives.tsx` | S89b | coral-specific | The connect action reads "Install Coral", "Start Coral" or "Open Coral" (S89b). |
| `web/src/pages/settings/GlobalShortcutControl.test.tsx` | S89 | coral-specific | GlobalShortcutControl tests find the switch by its new name 'Show Coral from anywhere' (S89). |
| `web/src/pages/settings/GlobalShortcutControl.tsx` | S89 | coral-specific | Global shortcut label and description name the app via useAppName() (S89). |
| `web/src/pages/settings/HarnessFixDialog.test.tsx` | S89 | coral-specific | HarnessFixDialog tmux test expects the full 'If Coral still can't find it, quit and reopen the Coral app.' sentence (S89). |
| `web/src/pages/settings/HarnessFixDialog.tsx` | S89 | coral-specific | Tmux setup hint in the harness fix dialog names the app via useAppName() (S89). |
| `web/src/server-selector-v2.test.tsx` | S89b | coral-specific | Queries follow the Coral onboarding copy (S89b). |
| `web/src/shell/AppShell.test.tsx` | S89 | coral-specific | Share-action tests now expect 'Coral server' in the read-only notice and in the sharing-off title (S89). |
| `web/src/shell/AppShell.tsx` | S89 | coral-specific | The header Share button's sharing-off reason (shareDisabledReason) now reads 'Sharing has been disabled for this <appName> server.' through useAppName() (default Coral) (S89). |
| `web/src/shell/CloseWindowDialog.test.tsx` | S89 | coral-specific | The last-window test now expects "Quit Coral?" and "...closing it quits Coral." (S89). |
| `web/src/shell/CloseWindowDialog.tsx` | S89 | coral-specific | The last-window close dialog's title and description now name the app via useAppName() ("Quit Coral?", "...closing it quits Coral.") instead of Omnigent (S89). |
| `web/src/shell/MarkdownRichTextViewer.test.tsx` | S89 | coral-specific | The agent-running warning tests match /Coral is still working/, both where the warning should show and where it should not (S89). |
| `web/src/shell/MarkdownRichTextViewer.tsx` | S89 | coral-specific | The agent-running warning in the markdown editor reads "<app name> is still working" through useAppName() instead of "Omnigent is still working" (S89). |
| `web/src/shell/NewChatDialog.test.tsx` | S81, S89 | coral-specific | The default-heading case expects Coral's display heading in the hero (S81). The expected tmux-unavailable warning text in the landing harness table now names Coral (S89). |
| `web/src/shell/NewChatDialog.tsx` | S81, S89 | coral-specific | The desktop default hero renders `CoralHero` (mark beside the heading); sibling, project and mobile branches are unchanged (S81). The tmux-unavailable harness hint says "If Coral still can't find it, quit and reopen the Coral app" using DEFAULT_APP_NAME, because harnessWarningMessage is a plain function that cannot call hooks (S89). |
| `web/src/shell/QuitDialog.test.tsx` | S89 | coral-specific | The quit dialog test now expects the "Quit Coral?" heading (S89). |
| `web/src/shell/QuitDialog.tsx` | S89 | coral-specific | The quit confirmation title now reads `Quit ${useAppName()}?` (Coral by default) instead of "Quit Omnigent?" (S89). |
| `web/src/shell/Sidebar.subagentHighlight.test.tsx` | S80 | coral-specific | Expects the Coral wordmark in the default sidebar brand (S80). |
| `web/src/shell/Sidebar.tsx` | S80, S89 | coral-specific | With no operator app name, the sidebar brand renders `CoralWordmark` instead of the Omnigent wordmark image; test ids unchanged (S80). The sidebar row menu's sharing-off Share tooltip now names the app through useAppName() (default Coral) instead of Omnigent (S89). |
| `web/src/themePalettes.generated.css` | S82 | coral-specific | Regenerated: the two `omni` blocks carry Coral's tokens; every other palette is byte-identical (S82). |
| `web/update-overlay.html` | S89 | coral-specific | The desktop update overlay window's title is now "Coral Update" instead of "Omnigent Update" (S89). |

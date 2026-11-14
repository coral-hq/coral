# Coral engineering findings: hosts, workspaces, worktrees, sandboxes, host-side execution, `.coral/` files, evidence collection points

Author role: Staff Engineer (Agent 3). Repo: `omnigent-ai/omnigent` at `2a9cbe2c2` (0.22.0.dev0). Read-only audit. Every Omnigent claim below cites a `path:line` I opened at HEAD. Anything not opened or not provable by reading is marked **UNVERIFIED**.

Verdict vocabulary: **Reuse** (as-is), **Extend** (add to an existing unit without changing its behaviour), **Modify** (change existing behaviour), **New**, **Replace**, **Remove**.

New seam IDs continue the deep dive's ledger: **W-S41 … W-S51** (section 8).

---

## 0. Summary for roadmap owners

1. **Worktree plumbing is solid and reusable as-is for the local case.** The host runs `git` with argv lists, validated ref names, a 3,600 s create budget, rollback, collision-free sibling directories, and owner-checked server proxies. Scheduled fires already show the request-free pattern Coral needs (`omnigent/server/scheduled/fire.py:1597-1641`). Coral should create run and agent worktrees itself, then bind sessions to them by passing `workspace=<worktree>` (no `git` options), so session deletes never delete Coral-owned branches (section 4.6).
2. **Two corrections to the deep dive.**
   - A server-initiated "run a command" path exists, but only per session. `POST /v1/sessions/{sid}/resources/environments/{env}/shell` is owner-only, goes through the runner, runs `env.shell()` in the session's `os_env` sandbox, and has a 120 s default timeout (`omnigent/server/routes/sessions/routes_resources.py:3257-3297` → `omnigent/runner/app.py:8296-8347` → `omnigent/inner/os_env.py:1056-1074`). It needs a live runner and an `os_env` spec. It cannot run sessionless work, such as fingerprints at `submit_handoff` for native modes, merges, resets, setup, or checks in a Coral-controlled checkout. **S40 is still needed.**
   - The host's HTTP filesystem API cannot read file contents, as the deep dive says. The **host tunnel frame `host.fs_request` op `list_or_read` can**, up to 10 MiB, confined to a root (`omnigent/host/connect.py:3793-3891`; `omnigent/workspace_fs.py:64, 194-216, 288-311`; server proxy `omnigent/server/routes/_host_filesystem.py:59-139`). Reading `.coral/workflows/*.yaml` and repo config for command detection is **Reuse**. Writing is not: `host.fs_write_request` only serves `github_*` ops (`connect.py:4392-4557`).
3. **An evidence-integrity hazard exists today.** The host's orphan reaper waits every 2 s on direct children it does not own (`connect.py:393, 1549-1596`). The worktree handlers pause it (`connect.py:4580, 4640, 4680`). The `fs_request`/`fs_write` handlers do **not** pause it (`connect.py:6027-6034`). Any Coral host op that runs a subprocess and trusts its exit code must run under `_run_host_subprocess_in_thread` (`connect.py:1611-1630`). Otherwise a stolen status can come back as exit 0, which is CPython's ECHILD fallback (UNVERIFIED empirically). Seam **W-S46**.
4. **Observation points per mode exist, and a precedent shows how to collect them.** `omnigent/runner/pr_observer.py:540-616` is already called from the four places Coral needs:
   - `claude-sdk` `sys_os_shell` (`tool_dispatch.py:7297-7307`);
   - headless executor tool completions, including Codex `commandExecution`/`fileChange` (`omnigent/runtime/harnesses/_executor_adapter.py:1106-1125, 1150-1185`);
   - the native PostToolUse relay (`omnigent/harnesses/claude_native/bridge.py:8233-8250`, also used by codex-native: `omnigent/harnesses/codex_native/app_server.py:3346-3355`);
   - managed MCP calls (`omnigent/tools/mcp.py:717-726`).

   `pr_reports.py` is a durable on-disk outbox that sends a session event and retries until acknowledged (`omnigent/runner/pr_reports.py:1-9, 52-150`). Coral's workspace fingerprints should reuse both patterns (W-S43, W-S44).
5. **Parallel code changes need a design correction.** Draft 4 §5.3 says the orchestrator "assigns one of the step's agents to resolve the conflict". A session's workspace is immutable (`omnigent/entities/conversation.py:202-212`), so that agent cannot work in the run worktree. Resolution must happen in the agent's own worktree by merging the run branch *into* the agent branch, followed by a clean re-merge. A second issue: evidence that agents collected in their own worktrees never matches the merged result's fingerprint. Verifying the merged result therefore needs Coral-run checks, or a post-merge verification slot (section 4.5).
6. **Long waits are mostly fine locally and risky in managed sandboxes.**
   - All three reapers skip in-flight work: SDK processes, the runner watchdog and native panes. Idle reaping leaves sessions resumable.
   - In managed sandboxes, keep-warm comes only from runner pongs (`omnigent/server/managed_host_keepalive.py:1-29, 176-185, 230-276`). Host-op work, such as a Coral-run check, is invisible to it.
   - Non-resumable providers relaunch a new generation that re-clones `<url>#<branch>` from labels (`omnigent/server/managed_hosts.py:353-366, 4062-4078`), so unpushed work is lost.
   - Needed: checkpoint pushes plus a host-keyed keep-warm lease (W-S45), and later relaunch-from-checkpoint (W-S49).
7. **Workflow files: the repository is canonical, and the server DB holds pinned versions and drafts.** Read through the existing `host.fs_request`. Write through one new host op confined to `<repo>/.coral/**`, with an expected-hash precondition. Runs never re-read the file; they pin a `coral_workflow_versions` snapshot (section 6).

---

## 1. Scope, sources and discrepancies

### 1.1 Discrepancies D1 to D4, as they touch this area

| ID | Status in my area | Evidence |
|---|---|---|
| D1 "sandboxes network on/off only" (Draft 4 §4.2, l.108) | **Confirmed false** (F26). `egress_rules` is a default-deny L7 allowlist on `linux_bwrap`/`darwin_seatbelt` (`omnigent/inner/datamodel.py:753-765`; `omnigent/inner/loader.py:855-862`). bwrap isolates the network namespace whenever an egress relay is active (`omnigent/inner/bwrap_sandbox.py:604-612`). **Where it applies:** the `os_env` helper (`sys_os_*`); the headless Codex worker (`omnigent/inner/codex_worker.py:131-195`); sandboxed terminals (`omnigent/inner/terminal.py:1670-1690, 1921-1939`). **Not** the Claude CLI's own traffic in `claude-sdk` (`omnigent/inner/claude_sdk_executor.py:1602-1607`). Signer-backed Codex rejects it (`codex_executor.py:4890-4894`; `codex_worker.py:118-121`). Native CLI provider traffic under a terminal egress sandbox: **UNVERIFIED**. Managed providers' network modes: **UNVERIFIED** (not opened). | as cited |
| D1 "idle reaping on long steps" (Draft 4 §4.2, l.109; §16) | **Refined.** In-flight work is protected by all three reapers (section 7.1). The real long-wait risk is managed-sandbox sleep and relaunch, plus host-op work that is invisible to keep-warm. A blanket S27 patch is not justified. Retest instead, and add W-S45. | section 7 |
| D1 "Coral-run checks: Coral runs commands in the step's workspace" (Draft 4 §6.2) | Feasible only with new host execution (S40 / W-S41). The session shell endpoint is a partial fallback (section 2.5). | section 5 |
| D1 "the engine records a fingerprint after each command" (Draft 4 §6.1, l.226) | The engine lives in the server, which has no workspace filesystem ("the server has no filesystem", `omnigent/server/schemas.py:1743-1745`). Fingerprints must be computed on the host, by the runner or the host daemon, and reported back. | section 5.4 |
| D1 "each agent works on its own branch of the run's worktree" (Draft 4 §5.3, l.166) | Imprecise. One worktree has one HEAD, and a branch can be checked out in only one worktree. Each code-changing agent needs **its own worktree** on its own branch, as §11 l.352 says. | section 4 |
| D2 `coral-requirements.md` missing | **Confirmed.** No such file under the repo (`find . -maxdepth 3 -name 'coral-requirements*'` is empty). Also missing: `designs/SESSION_GIT_WORKTREE.md`, cited by `omnigent/host/git_worktree.py:6`, `_host_worktree.py:7` and `schemas.py:1471`; and `designs/SESSION_WORKSPACE_SELECTION.md`, cited by `routes/hosts.py:1614-1616` and `tool_dispatch.py:7554-7555`. Neither is in `designs/` (31 files listed). | `ls designs` |
| D3 profiles in localStorage; `/workflows` vs `/schemas` | Storage implication only: workflow YAML and layout must not live in browser storage. Omnigent's canvas layout is per-viewer `localStorage` (deep dive §14.4, `web/src/canvas/canvasStorage.ts:1-9`, not re-opened). Workflow files live in the repo, with DB versions (section 6). | section 6 |
| D4 EGM persistent session and per-member input scoping | Workspace implication: goldfish reviewers need a **scoped input workspace** that holds only the document. That needs (a) `host.create_dir`, which exists (`connect.py:3216-3287`), plus (b) a file-write host op (W-S41 op `files.materialize`). The elephant's persistent session keeps one workspace across loop passes, which bind-mode sessions already allow. | section 5.2 |

### 1.2 Deep dive claims verified at HEAD (my area)

| Deep dive claim | Result |
|---|---|
| §13: `create_worktree(...)`, `<parent>/<repo>-worktrees/<sanitized>`, 3,600 s (`git_worktree.py:29, 419-448, 510-565`) | Confirmed exactly. |
| §13: proxies at `_host_worktree.py:190-357` | Confirmed (create 190-257, remove 260-306, list 309-357). |
| §13: `SessionGitOptions` (`schemas.py:1455-1514`), managed rejection (`schemas.py:2012-2013`) | Confirmed. The raise is at `schemas.py:2011-2013`. |
| §13: fire per-run branch `worktree-<hex12>` (`fire.py:1613-1638`) | Confirmed: `fire.py:1613-1641`, branch name at 1627. |
| §13: `_remove_session_worktree_best_effort` (`helpers.py:10294`) | Confirmed. It also returns early for any host with `sandbox_provider` (`helpers.py:10353-10358`). |
| §9.1: native relay best-effort, 1 s curl | Confirmed: `tool_observer_hook.py:36` (`max_time=1`), hook `timeout: 3` (l.39). |
| §9.2: "No server-initiated run-this-command API" | **Partly incorrect** (section 0, item 2). |
| §14.4: host FS API lists and creates directories only (`hosts.py:1599-1617, 1729-1745`) | True for HTTP. The `host.fs_request` frame reads contents (section 2.4). |
| F13 reaper locations | Confirmed (section 7.1). |
| F24 roots-only relaunch (`app.py:4259-4296`, 4273) | Confirmed: `roots = [conv for conv in held if conv.kind != "sub_agent"]` at `omnigent/server/app.py:4273`. |
| S40 handler anchor `connect.py:4559` | Confirmed: `_handle_create_worktree`. |

---

## 2. Verified current capabilities

### 2.1 Host daemon and frame transport

- **Frame kinds.** `HostFrameKind` enumerates all host frames (`omnigent/host/frames.py:213-279`): stat, list_dir, create/remove/list worktree, create_dir, fs_request, fs_write_request and others. Unknown frames are silently ignored by the host (`connect.py:5834-5865`). A new server-to-host frame sent to an older host therefore only **times out**. Gate on a capability token, as `CAP_WORKTREE_CREATE_BUDGET` does (`frames.py:90-109`; checked at `_host_worktree.py:233`).
- **Concurrency.** Every inbound frame runs on its own task (`connect.py:5765-5774`), so a long handler does not block the receive loop. On disconnect, in-flight handler tasks are **cancelled** (`connect.py:5776-5783`). A worker thread keeps running, but its reply is lost. Long host jobs therefore need job ids and a re-query path (section 5.3).
- **Subprocess ownership.** The host is a subreaper. `_orphan_reaper_loop` sweeps every `_ORPHAN_REAP_INTERVAL_S = 2.0` s and `waitpid(WNOHANG)`s every unowned direct child (`connect.py:393, 1549-1596`). `_host_subprocess_op()` and `_run_host_subprocess_in_thread()` pause it (`connect.py:1598-1630`). The worktree handlers use the guard (`connect.py:4580, 4640, 4680`). **The fs handlers do not** (`connect.py:6027-6034`).
- **Server side.** Each request type has a `pending_*` future map on `HostConnection` (`omnigent/server/host_registry.py:506-561`). Results are routed by request id in the tunnel route (`omnigent/server/routes/host_tunnel.py:999-1000` for create-worktree results, `1180` for fs results).
- **Sharding.** `configure_host_sharding` / `host_absent_error` (`omnigent/server/routes/_host_launch.py:161-212`). In a sharded deployment, a host's tunnel lives on exactly one replica. Engine-originated host ops must run on that replica (risk R-W7).

### 2.2 `omnigent/host/git_worktree.py` (795 lines). **Reuse**, with small **Extend** (W-S47)

| Function | Lines | Behaviour that matters to Coral |
|---|---|---|
| `validate_branch_name` | 69-101 | git ref-format checks. It rejects components starting with `.`, `..`, `@{`, `.lock` and leading `-`. A `coral/r-<id>/...` scheme passes. |
| `_sanitize_dirname` | 104-112 | `/` becomes `-`. `coral/r-ab/base` maps to the directory `coral-r-ab-base`. |
| `_exec_git` | 115-136 | Uses `LC_ALL=C` and `GIT_TERMINAL_PROMPT=0`, so a credential prompt fails at once. |
| `_main_work_tree` | 245-280 | Always anchors at the **main** work tree. A worktree created from a run worktree is still a sibling under `<repo>-worktrees/`. |
| `list_worktrees` | 331-399 | Parses `HEAD` per record but **does not return it**: `WorktreeInfo` has no head field (`283-305`). |
| `_resolve_worktree_path` | 419-448 | Path is `<parent>/<repo>-worktrees/<dir>`, with up to 50 `-N` suffixes. The repo's parent directory must be writable. There is no configurable root. |
| `create_worktree` / `_create_worktree` | 510-708 | Two modes: `-b new` from `base_branch` (or HEAD), or an existing branch. No `--detach` mode. A pinned-commit path applies when the picked directory is a subdirectory. Rollback is built in. **The result has no HEAD commit** (`CreatedWorktree` 493-507). |
| `remove_worktree` | 738-795 | `worktree remove --force`, then optionally `branch -D`. It verifies the path is the worktree root. |

There is **no merge, commit, reset, fetch, push or status op**. The only git ops the host runs are worktree create, list and remove, plus read-only git inside `WorkspaceReader` and the GitHub `pr_resource` writes.

### 2.3 Server worktree proxies, session git options, request-free precedent

- **Proxies.** `create_worktree_on_host` / `remove_worktree_on_host` / `list_worktrees_on_host` (`_host_worktree.py:190-357`).
  - Create timeout is `3600 + 150` s for budget-capable hosts and 150 s otherwise (`_host_worktree.py:31-37, 233-243`).
  - Errors: `WorktreeHostUnavailableError` → 409; `WorktreeProxyError` → 400 (`_host_worktree.py:78-109`).
  - `WORKTREE_ROOT_LABEL_KEY = "omnigent.git.worktree_root_sha256"` with `worktree_root_fingerprint`/`recorded_worktree_root` (`_host_worktree.py:40-75`) records root identity for safe cleanup.
- **Session API.** `SessionGitOptions` supports create mode and bind mode (`existing_worktree=True`, which records `git_branch` without running git) (`schemas.py:1455-1514`). `git` requires `host_id` or `project_id` (`schemas.py:1738-1752`). Managed sessions reject `git` (`schemas.py:2011-2013`).
- **Create flows.**
  - JSON create: `omnigent/server/routes/_sessions/orchestration.py:12072-12160`. The workspace is validated **only when `host_id` is set** (12073-12082). A child create without `host_id` stores `body.workspace` as-is.
  - Bundle create: `routes_core.py:1660-1735`.
  - Both need a FastAPI `Request` (`_create_session_worktree`, `helpers.py:10217-10283`; `_require_host_conn_for_worktree`, `helpers.py:10182-10214`).
- **Request-free precedent.** `fire._create_session_resources` (`fire.py:1597-1693`): `create_worktree_on_host(..., branch_name=f"worktree-{uuid…[:12]}")`, labels `SCHEDULED_TASK_WORKTREE_SOURCE_LABEL_KEY` and `WORKTREE_ROOT_LABEL_KEY`, `create_conversation(host_id, workspace, git_branch, labels)`, and rollback through `_remove_session_worktree_best_effort` (`fire.py:1673-1691`). Ownership re-check for continued sessions: `fire.py:1040-1055`. Unused-session cleanup: `fire.py:1175-1200`.
- **Cleanup hazards.**
  - Session delete with `delete_branch=true` removes the worktree **and** branch for any session that has `git_branch`, `workspace` and `host_id` (`routes_events.py:4166-4189`). The only guards are "another live session shares it" (`helpers.py:10360-10386`, `has_other_live_session_in_workspace` `conversation_store/__init__.py:2412`) and "host is a sandbox" (`helpers.py:10353-10358`).
  - A user deleting a run-owned step session could therefore delete Coral's agent branch. Mitigation in section 4.6.

### 2.4 Host filesystem: HTTP vs frames

| Path | What it does | Verdict for Coral |
|---|---|---|
| `GET /v1/hosts/{id}/filesystem[/{path}]` (`routes/hosts.py:1561-1727`) | Owner-only directory listing through `host.list_dir`. No file content. | **Reuse** for the repo picker. |
| `POST /v1/hosts/{id}/directories` (`hosts.py:1729`) → `_handle_create_dir` (`connect.py:3216-3287`, `os.makedirs(exist_ok=False)`) | Create a folder. | **Reuse** for plain-folder workspaces and EGM scoped inputs. |
| `GET /v1/hosts/{id}/worktrees?path=` (`hosts.py:2422-2485`) | Owner-only worktree listing. | **Reuse** for diagnostics and run recovery. |
| `host.fs_request` (`frames.py:1147-1175`; `_handle_fs_request` `connect.py:3793-3891`; `_dispatch_fs_op` `connect.py:4294-4390`; proxy `read_workspace_from_host` `_host_filesystem.py:59-139`, **20 s timeout** at l.30) | `WorkspaceReader` ops: `list_or_read` (dir listing or file ≤ 10 MiB, confined by `_resolve_workspace_path`), `changes`, `diff`, `search`, `repository_branches`, GitHub reads. If `workspace` is an absolute **file** and `path` is empty, it reads that file (`connect.py:3828-3831`). Reader instances are cached, 8 per host (`connect.py:250`), and each starts a `FilesystemRegistry` (`workspace_fs.py:172-178`). | **Reuse** for `.coral/workflows/*.yaml`, layout files and repo-config detection. `session_id` must be a non-empty string (`frames.py:3175-3190`); pass `coral:<binding>`. |
| `host.fs_write_request` (`frames.py:1177-1214`; `connect.py:4392-4557`; proxy `write_workspace_from_host` `_host_filesystem.py:142-226`) | Only the `github_*` ops. An unknown op raises `ValueError` → 400 `invalid_request` (`connect.py:4557`), which **fails fast** on old hosts. | **Extend** with one op (`coral_file_write`, W-S50), or fold it into W-S41. |

### 2.5 Session-scoped file and shell APIs (through the runner)

- **Read:** `GET /v1/sessions/{sid}/resources/environments/{env}/filesystem/{path}` with host fallback (`routes_resources.py:3048-3157`).
- **Write:** `PUT …/filesystem/{path}` (`routes_resources.py:3158-3189`) → runner `write_environment_file` (`omnigent/runner/resource_routes.py:1845-1885`). A PUT first **reconnects/relaunches the runner** ("saving needs a runner to enforce the environment's write policy", `routes_resources.py:2514-2530`). The web hook `useWriteFileContent` always targets a session (`web/src/hooks/useWriteFileContent.ts:41-60`).
- **Shell:** `POST /v1/sessions/{sid}/resources/environments/{env}/shell`. It is **owner-only** and "passes no policy or approval gate" (`routes_resources.py:3257-3297`). The runner runs `env.shell(command, timeout)` (`omnigent/runner/app.py:8296-8347`) and returns `{stdout, stderr, exit_code, timed_out, cwd}`.
  - Default timeout is 120 s; any int ≥ 1 is accepted (`os_env.py:1056-1074`).
  - It requires the session spec to have `os_env`. `_require_os_env` raises 404 only when the spec exists without `os_env` (`resource_routes.py:1023-1030`).
  - Behaviour over the runner tunnel for long timeouts: **UNVERIFIED**. Whether native-mode specs carry `os_env`: **UNVERIFIED**.
  - **Verdict:** **Reuse** as a fallback for Coral-run checks while the step's runner is alive. Its gaps are listed in section 5.1, so it cannot replace S40.

### 2.6 Per-mode observation points (where fingerprints can be computed)

| Mode | Code point (verified) | Has before/after? | Exit status | Call id |
|---|---|---|---|---|
| `claude-sdk` | Native Bash/Read/Edit/Write are not exposed; the base tools are only Skill, ToolSearch and AskUserQuestion (`claude_sdk_executor.py:2571-2585, 3036-3043`). `sys_os_*` go through the server MCP endpoint (TOOL_CALL/TOOL_RESULT, `orchestration.py:13239-13258`) to runner `/mcp/execute` (`omnigent/runner/mcp_routes.py:111-375`), then `execute_tool` (`tool_dispatch.py:6960-7309`) and `_execute_os_env_tool` (`tool_dispatch.py:7656+`). The post-execution hook already exists for `sys_os_shell` (`tool_dispatch.py:7297-7307`). | Both can be computed in the runner around `_execute_os_env_tool`. | Shell result JSON carries `exit_code` (shape per `os_env.shell`). | `execute_tool` takes **no call id** (`tool_dispatch.py:6960-6981`). The server passes an optional MCP operation id (`orchestration.py:12850-12866`). Whether Claude's `tool_use_id` reaches the server MCP request: **UNVERIFIED**. |
| `codex` (headless) | `_codex_builtin_tool_request` (start) and `_codex_builtin_tool_completion` (`omnigent/inner/codex_executor.py:2774-2883`) produce `ToolCallRequest`/`ToolCallComplete` with `internally_executed` metadata. These are consumed in `_executor_adapter.py:1106-1125` (request, cached in `_pr_tool_calls`) and `1150-1185` (complete, calls `observe_tool_completion(source="sdk")`). | Before at request, after at complete. Parallel items may interleave. | `exitCode` is folded into the result text `"[exit code: N]"` with status ERROR; `ToolCallComplete` has **no structured exit_code** (`codex_executor.py:2850-2858`). | Codex item id → `call_id`. |
| `claude-native` / `codex-native` | PostToolUse observer hook (`omnigent/native/tool_observer_hook.py:14-39`) → relay `/hook/observe-tool` (`claude_native/bridge.py:8233-8250`) → `pr_observer.observe_hook` + runner `file_change_observer` (`omnigent/runner/app.py:5406-5440`). Codex-native installs the same observer (`codex_native/app_server.py:3346-3355`; `codex_native/hook.py:61-62`; forwarder relay `codex_native/forwarder.py:8068`). | After only, best-effort (1 s curl). | In `tool_response` (shape per harness). | `tool_use_id` in the payload (`pr_observer.py:609-616`). |
| Engine (server) | `submit_handoff` intercept (deep dive S10). There is no filesystem here, so it must call the host (W-S41 `fingerprint`). | Authoritative "final". | n/a | n/a |

**Durable reporting precedent.** `SessionPrRegistry` is a per-session JSON file under `data_dir()/github/session-prs` (`omnigent/runner/session_prs.py:84`). `PullRequestReporter` sends the `external_pull_requests` event to `POST /v1/sessions/{id}/events` and retries until a 2xx (`pr_reports.py:52-150`). The server handles the event type at `routes_events.py:2931-2933`, with the constant in `_sessions/common.py:165`. `notify` is a no-op in processes without a server client, such as harness subprocesses; entries stay on disk "for the next runner" (`pr_reports.py:144-165`).

### 2.7 Managed sandboxes

- **Identity.** The host identity is durable and the sandbox is not. A relaunch is a new sandbox *generation* under the same `host_id` (`managed_hosts.py:11-15`). `relaunch_managed_host` re-clones the create-time repos ("workspace contents of the dead generation are gone") (`managed_hosts.py:3964, 4062-4078`). The repo sources are labels `omnigent.sandbox.repo.<i>` = `<url>[#<branch>]` (`managed_hosts.py:344-366`). Clients cannot write the `omnigent.sandbox.` label namespace (`managed_hosts.py:344-347`).
- **Resume vs relaunch.**
  - Wake resumes in place only if `launcher.capabilities.resume_stopped` (`managed_hosts.py:4535, 4643`).
  - Resume-capable: `databricks_sandbox` (252), `daytona` (227), `islo` (199), `kubernetes` (1256), and `microsandbox` (class var `can_resume=True`, `microsandbox.py:474`).
  - Explicitly not resumable: `modal` (`modal.py:219`), `e2b` (`e2b.py:260`). Others default to False (`onboarding/sandboxes/base.py:516`; derived capability 518-540).
  - Exhaustive per-provider list: partially verified.
- **Keep-warm.**
  - `sandbox.keep_warm_s` maps to in-sandbox `runner.idle_timeout_s`, from 1 s to 30 days (`managed_hosts.py:1286-1338`).
  - The runner reports `keep_warm` on each pong (`omnigent/runner/_entry.py:2077-2097`; `busy_check.py:64-75`).
  - The server refreshes the provider only while the latest report is not `False`, keyed by **runner_id** and resolved to host through conversations (`managed_host_keepalive.py:137-185, 230-276`). `record_work_dispatched` marks server-dispatched work as warm (`managed_host_keepalive.py:158-173`).
  - With **no runner connected, nothing calls `touch`**.
- **Git credentials.** Managed sandboxes install a GitHub `credential.helper` that fetches the owner's token per operation (`omnigent/git_credential_github.py:1-35`; installed by the host, `connect.py:6331-6340`). Checkpoint pushes to github.com are therefore feasible. Other forges: **UNVERIFIED**.
- **Clone branch rules.** A commit SHA in `#<branch>` is rejected ("pin commits via git worktree options instead", `managed_hosts.py:1022-1040`), but git options are rejected for managed sessions (`schemas.py:2011-2013`). That is an inconsistency inside Omnigent, which S28 / W-S49 resolves.

### 2.8 Reapers and idle

| Reaper | Default | Override | Skips | Location |
|---|---|---|---|---|
| SDK harness subprocess | 3600 s (`process_manager.py:131`) | `OMNIGENT_HARNESS_IDLE_TIMEOUT_S`, 0 disables (`138-173`) | `_in_flight_response_ids` (`1591-1603`) | `omnigent/runtime/harnesses/process_manager.py` |
| Runner idle watchdog | 3600 s (`_entry.py:62`) | `runner.idle_timeout_s` in config, 0 disables (`_entry.py:162-199`) | `has_active_work`, which covers turns, Claude prompt waiters, async tasks, timers, **pending approvals**, native panes, background shells and native turns (`runner/app.py:1616-1669`; monitor `_entry.py:275-323`) | runner |
| Native pane | Runner idle default, env `OMNIGENT_NATIVE_PANE_IDLE_TIMEOUT_S` (`pane_reaper.py:85-87, 110-137`) | **Sub-agent panes are capped at the native default** (`pane_reaper.py:140-152`) | Busy: in-flight turn, running, or attached tmux client; reap is pane-scoped and "leaving the session resumable" (`pane_reaper.py:160-275`) | `omnigent/terminals/pane_reaper.py` |
| Managed sandbox | `keep_warm_s` → runner idle | deployment-wide | runner busy or grace | above |
| Host offline hold | `HOST_OFFLINE_HOLD_S = 72 h` for mid-turn sessions (`orchestration.py:8630-8641`) | none | n/a | server |
| Relaunch after host return | Root sessions only (`app.py:4259-4296`) | n/a | sub-agents skipped (4273) | server |

All are deployment-wide. There is no per-session override (confirms F13).

### 2.9 Per-worktree setup

**None exists.** A grep for `worktreeinclude|setup_command|post_create|worktree_setup` over `omnigent/` and `web/src` finds only `_create_session_worktree` call sites. Polly creates worktrees by instructing the model ("work only inside `.worktrees/<task_id>`", `examples/polly/skills/fanout/SKILL.md:12-21`): sessions share the parent cwd and isolation is only requested. Coral replaces this with server-created worktrees and session binding, so isolation is enforced by the session workspace and its sandbox.

### 2.10 Per-session workspace on a shared runner (deep dive §8.2 "verify")

- The runner resolves cwd **per session**: `_session_runtime_cwd(session_id)` returns the session snapshot's `workspace`, else the runner workspace (`runner/app.py:2330-2340, 2376-2380`). Tool dispatch passes it as `runner_workspace` (`runner/app.py:6814`), and `_effective_runner_os_env_spec` makes it authoritative (`tool_dispatch.py:7546-7599`).
- A child create without `host_id` stores any `workspace` string **unvalidated** (`orchestration.py:12072-12082`).
- So children with their own worktree on the parent's runner are **mechanically plausible**. Whether native panes, terminals and the sandbox's write roots follow a child's workspace is **UNVERIFIED**, and so is whether this is supported or accidental. Treat it as unsupported until a phase 2 contract test proves it (section 11).

### 2.11 Linked-worktree git metadata and sandboxes

A linked worktree's `.git` is a file that points into `<main>/.git/worktrees/<name>`. Commits write objects into `<main>/.git/objects`. No sandbox code mentions `git-common-dir` or `worktree`; the only hit is a comment at `inner/terminal.py:1004`.

**UNVERIFIED and important:** whether a sandboxed session (`os_env.sandbox` with write roots equal to its cwd) can `git commit` inside a linked worktree. If it cannot, engine-owned commits (section 4.3) are mandatory, which is also the safer design.

---

## 3. Gap matrix

| Capability Coral needs | Today | Verdict | Where |
|---|---|---|---|
| Create run and agent worktrees on a local host | `create_worktree_on_host` | **Reuse** | `_host_worktree.py:190-257`; pattern `fire.py:1597-1693` |
| Bind sessions to Coral worktrees | `workspace=<path>` with `host_id` (validated), or bind mode | **Reuse** | `orchestration.py:12072-12160` |
| Start commit on create | not returned | **Extend** (W-S47) or one extra op | `git_worktree.py:493-508, 704-708` |
| Detached checkout for checks | none | **Extend** (W-S47) | `git_worktree.py:655-670` |
| Configurable worktree root | none | **Extend** (W-S47, optional) | `git_worktree.py:419-448` |
| Commit, merge, abort, reset, salvage, fetch, push, branch ops | none | **New** (W-S41 ops) | new `coral/host_ops/git_ops.py` |
| Workspace fingerprint (git and plain folder) | none; `GitFilesystemRegistry` runs porcelain status only (`filesystem_registry.py:1260-1340`) | **New** | `coral/evidence/fingerprint.py` (host-side) |
| Sessionless command execution (checks, setup) | session shell endpoint only | **New** (W-S41 `exec` jobs); **Reuse** the session shell as fallback | section 5 |
| Read `.coral/` files and repo config | `host.fs_request list_or_read` | **Reuse** | `_host_filesystem.py:59-139` |
| Write `.coral/` files | none | **New** op (W-S50 / W-S41) | `connect.py:4449-4557` pattern |
| Per-command observations from runner/harness | `pr_observer` hard-wired | **Extend** into an observer registry (W-S43) | `tool_dispatch.py:7297`; `_executor_adapter.py:1171`; `bridge.py:8234`; `app.py:5406` |
| Durable observation transport | `pr_reports` pattern | **Extend**: new event type (W-S44) | `routes_events.py:2931`; `common.py:165` |
| Structured Codex exit code | folded into text | **Extend** metadata (part of W-S43) | `codex_executor.py:2850-2883` |
| Reaper safety for host subprocess exit codes | fs handlers unguarded | **Modify**: bug fix (W-S46) | `connect.py:6027-6034` |
| Sandbox keep-warm during host ops and gates | runner-keyed only | **Extend** (W-S45) | `managed_host_keepalive.py:176-276` |
| Worktrees inside managed sandboxes | rejected at schema | **Extend** (W-S49 = S28) | `schemas.py:2011-2013` |
| Relaunch from a checkpoint branch | re-clones the create-time ref | **Extend** (W-S49) | `managed_hosts.py:353-366, 4062-4078` |
| Protect Coral branches from session-delete cleanup | none | **Avoid** (no `git_branch` on run sessions) or **Extend** (W-S48) | `routes_events.py:4166-4189` |
| Per-worktree setup | none | **New** (Coral, uses W-S41 `exec`) | section 4.7 |
| Egress allowlists for steps | `egress_rules` | **Reuse** (rules team) | `datamodel.py:753-808` |
| Long-step reaper exemptions | in-flight protected | **Retest only** (S27); W-S51 only if retests fail | section 7 |

---

## 4. Design 1: run and agent worktree lifecycle

### 4.1 Topology and naming

- **Repo binding.** This is the user-chosen `(host_id, repo_root)` pair, created with the existing picker (`/v1/hosts/{id}/filesystem`, `/worktrees`). Store it in `coral_repo_bindings` (section 9). Optional anchor: `Project.config` already carries "host, workspace, … git base-branch" hints, but they are client-owned and unenforced (`omnigent/entities/project.py:17-43`). Link the binding to a project; do not rely on it.
- **Branch scheme.** Git cannot hold both `x` and `x/y` as refs (deep dive §13), so every branch is a **leaf under one run directory**:
  - Run branch: `coral/r-<run12>/base`.
  - Agent branch: `coral/r-<run12>/a-<node8>-<scope8>-m<roster>-t<attempt>`. `scope8` is the per-item scope hash for repeat-for-each.
  - Salvage refs: `refs/coral/salvage/<attempt_id>`. These are outside `refs/heads`, so they are hidden from branch pickers and avoid D/F clashes.
  - Check worktrees: detached HEAD, no branch.
  - All names pass `validate_branch_name` (`git_worktree.py:69-101`).
- **Directories.** The default is Omnigent's sibling layout `<parent>/<repo>-worktrees/coral-r-<run12>-…` (`git_worktree.py:419-448`). W-S47 adds an optional `worktree_parent` so a deployment can use `~/.omnigent/coral/worktrees/<repo-hash>/` when the repo's parent is not writable. That condition is otherwise a hard failure (`git_worktree.py:653`).
- **Single-writer invariant.** At most one *code-changing* slot is active per worktree at a time. Read-only slots, such as reviewers and the orchestrator, may share the run worktree. The validator enforces this. It is what makes reset-on-restart safe.

### 4.2 Lifecycle (engine effects; each is an idempotent `coral_effects` row)

```
Run start
  E1 worktree.create_run   create_worktree_on_host(repo_root, "coral/r-X/base", base_ref)          [Reuse]
  E2 ws.head               record start_commit (W-S47 returns it; else W-S41 op git.head)        [Extend]
  E3 ws.setup              W-S41 exec job: copy-includes + setup commands (4.7)                  [New]
  E4 session.create(orch)  host_id + workspace=<run wt>, NO git options; orchestrator write tools
                           denied by policy (deep dive §9.3 item 6)                               [Reuse]
Step activation (single code-changing agent)
  E5 ws.fingerprint L2     baseline; activation.start_commit = HEAD                              [New]
  E6 session.create(step)  workspace=<run wt>                                                    [Reuse]
Step activation (k code-changing agents, or parallel code steps)
  E7 worktree.create_agent create_worktree_on_host(repo_path=<run wt>, "coral/r-X/a-…", base="coral/r-X/base")
                           (resolves to the main repo; base resolves locally)                   [Reuse]
  E8 ws.setup per agent wt                                                                      [New]
  E9 session.create(slot)  workspace=<agent wt>                                                 [Reuse]
Handoff accepted
  E10 ws.commit_all        in the slot's worktree, with trailers Coral-Run/Coral-Attempt/Coral-Op [New]
Step close / parallel join (only if >1 writer)
  E11 ws.merge (serial)    into the run worktree, roster order; abort on conflict                [New]
  E12 checks               Coral-run checks on the merged result (4.5)                           [New]
Run end / retention
  E13 worktree.remove      agent worktrees after merge; run worktree per policy;
                           branches kept for N days or until PR merged                          [Reuse]
```

The ownership labels on each session are `coral.run_id`, `coral.slot_id` and `coral.worktree_root_sha256`. That last label mirrors `WORKTREE_ROOT_LABEL_KEY` (`_host_worktree.py:40-51`) and the fire ownership check (`fire.py:1040-1055`).

### 4.3 Engine-owned commits (recommended)

Agents edit files, and the engine commits at accepted handoffs. Reasons:

- (a) Sandboxed commits in linked worktrees are uncertain (section 2.11).
- (b) Commits become idempotent and traceable. Trailers allow `git log --format=%(trailers)` lookups and make a retried `commit_all` return the existing commit.
- (c) Evidence can diff `start_commit..handoff_commit` for the test-integrity rule (deep dive §9.3 item 2).

**Decision needed (open question):** whether engine commits on `coral/*` branches skip repo commit hooks (`-c core.hooksPath=/dev/null`). Recommendation: skip them, because hooks are not evidence. Coral-run checks and the final PR's CI are. Record the choice in the run log. Agents must never be allowed `--no-verify` on user branches (Transluce, deep dive §9.3).

### 4.4 Restart safety

- At activation start, record `start_commit` and the L2 fingerprint.
- When a slot restarts after runner loss (Draft 4 §7.8):
  1. `ws.salvage(root, ref=refs/coral/salvage/<attempt_id>)`. This snapshots uncommitted state through a temporary index, `write-tree` and `commit-tree`, so nothing is silently destroyed and the user can recover partial work.
  2. Abort any in-progress merge or rebase (best-effort).
  3. `git reset --hard <start_commit>`.
  4. `git clean -fd`, **without `-x`**, so ignored dependencies such as `node_modules` and `.venv` survive.
  5. Create a new session bound to the same worktree path. Workspaces are immutable per session (`entities/conversation.py:202-212`), so the binding is new; the path is not.
- **Take-over guard.** If the user took over the slot (Draft 4 §13), skip the automatic reset and pause for a decision.
- **Plain folders.** Use a shadow repo under `data_dir()/coral/shadow/<binding>.git` with `--work-tree=<folder>`, a default exclude list and an optional `.coralignore`. A snapshot is `add -A` plus `commit-tree` in the shadow repo. A restore is `checkout -f <snap> -- .` plus `clean -fd`. The same shadow repo gives plain-folder fingerprints (section 5.4). V1 rule: more than one code-changing agent on a plain folder is a validation error.

### 4.5 Merging parallel code changes (corrects Draft 4 §5.3)

1. **Precondition.** Each agent branch carries the engine commit from E10. The run worktree is clean: its L2 fingerprint equals the tree of HEAD.
2. **Serial merges.** For each agent branch in roster order, run `ws.merge(root=<run wt>, ref=<agent branch>, no_ff=true, message=…)`.
   - **Clean merge:** record `merge_commit`.
   - **Conflict:** collect `git diff --name-only --diff-filter=U`, then `git merge --abort`, so the run worktree is never left conflicted.
3. **Conflict resolution happens in the agent's own worktree.** A session's workspace cannot be moved, so the resolver works where it already is.
   - The engine runs `ws.merge(root=<agent wt>, ref="coral/r-X/base", leave_conflicts=true)`.
   - It instructs the assigned agent to resolve the conflicts and call `submit_handoff`.
   - It verifies `git ls-files -u` is empty and `git diff --check` passes.
   - It runs `commit_all`, then re-merges into the run worktree. That merge is now clean.
   - Attempts count toward the step's attempts. When they run out, the failure path applies, pausing the run and asking the user by default.
4. **Evidence semantics (design decision required).** Each agent's "done when" commands ran in its own worktree. Their before-fingerprints therefore never equal the **merged** run worktree's fingerprint, so Draft 4's "evaluated on the merged result" cannot be satisfied by agent-run commands. Options:
   - **(a) recommended:** evaluate per-agent "done when" against each agent's worktree before merging. Make **Coral-run checks mandatory by default** for any step that merges more than one writer, and evaluate them on the merged result (E12).
   - **(b)** after merging, spawn a short verification slot bound to the run worktree.

   This answers deep dive §20.2 Q5 for code-changing multi-agent steps.
5. **Repository traits.** Before E1, `ws.probe` detects submodules (`.gitmodules`), LFS (`.gitattributes` `filter=lfs` and `git lfs` presence), sparse checkout and a shallow clone.
   - Submodules: refuse in v1, or require a setup step that runs `git submodule update --init`.
   - LFS without `git-lfs` installed: refuse, because worktrees would hold pointer files.
6. **Nested in-session worktrees** (deep dive §9.2): `claude-sdk` exposes no native Agent or worktree tools (`claude_sdk_executor.py:2571-2585`), but `sys_os_shell("git worktree add …")` remains possible. Two controls:
   - Deny `git worktree` and `git checkout`/`switch` of non-Coral branches for run-owned sessions by policy (rules team).
   - Treat any change to the branch HEAD that the engine did not create (`HEAD` moved off `coral/r-X/…`) as an evidence violation, detected by `ws.fingerprint`, which reports `head`/`branch`.

### 4.6 Cleanup and protection

- Run-owned sessions are created **without `git` options**, only `host_id` + `workspace` (validated by `_validate_session_workspace`, `orchestration.py:12073-12082`). They therefore have no `git_branch`, and the session-delete path (`routes_events.py:4166-4189`) cannot delete Coral branches.
  - Cost: the sidebar branch chip does not show. If product wants the chip, add **W-S48**: skip `_remove_session_worktree_best_effort` for sessions labelled `coral.run_id`.
- Coral removes worktrees itself, reusing `remove_worktree_on_host` and the "shared by another live session" check (`helpers.py:10360-10386`) through a request-free call, as `fire.py:1673-1691` does.
- **Retention.** Remove agent worktrees after a successful merge. Keep agent branches until the run ends, then delete them. Keep the run branch until the user deletes it or a PR merges.
- **Disk budget.** Count live Coral worktrees per binding and refuse new ones above a configurable cap. `create_worktree` only limits name collisions (`_MAX_DIR_COLLISION_SUFFIX = 50`, `git_worktree.py:42`).

### 4.7 Per-worktree setup

- **File.** `<repo>/.coral/repo.yaml`, committed and confirmed by the author like command patterns:

  ```yaml
  setup:
    include: [".env", ".env.local", "config/local/*.json"]   # copied from the main work tree, only if gitignored
    run:
      - pnpm install --frozen-lockfile
    timeout_s: 1800
  checks:                     # repository checks (Draft 4 §6.2), detected then confirmed
    test:   { run: "pnpm test --reporter=junit", reports: ["reports/junit*.xml"] }
    lint:   { run: "pnpm lint" }
    format: { run: "pnpm prettier --check ." }
  ```
- If no `.coral/repo.yaml` exists, read Claude Code's `.worktreeinclude` as a fallback include list (deep dive §13, W-67).
- **Execution.** `ws.files.copy_include` and `exec` jobs through W-S41 (section 5) run after E1/E7 and before the session is created. Failure pauses the run as an infrastructure pause (Draft 4 §7.8). Record the setup output tail and lockfile hash in the run log. Skipping setup when the lockfile hash is unchanged is an optimization for later.

### 4.8 Managed sandboxes (S28 → W-S49)

Two stages:

- **Stage A (no relaxation).** After `launch_managed_host` registers, the sandbox host is an ordinary host connection, so the engine can send worktree frames to it and run W-S41 ops.
  - Open point: binding further sessions to that host with `host_type="external"` + `host_id=<managed id>` + `workspace=<path in sandbox>`. `resolve_host_launch` passes `sandbox_provider` into the profile check (`_host_launch.py:290-297`), but an end-to-end create against a managed host id is **UNVERIFIED**.
  - If it is rejected, W-S49 relaxes `schemas.py:2011-2013` to allow bind mode, or adds an engine-only path.
- **Stage B (generation-safe).**
  - At every accepted handoff, run `ws.push(root, remote="origin", refspec="coral/r-X/base", force_with_lease)` (GitHub credential helper, section 2.7).
  - On relaunch or wake into a new generation, the engine runs `ws.fetch` and `create_worktree(existing_branch=True)` at the same branch.
  - Same-path restoration lets existing sessions stay bound only if the clone path is identical across generations (**UNVERIFIED**). Otherwise create new sessions from the last handoff.
  - Optionally point `omnigent.sandbox.repo.<i>` at `<url>#coral/r-X/base` so Omnigent's own relaunch clones the checkpoint. Coral runs in-server and can write server-internal labels, but this crosses into Omnigent's namespace, so it is a seam.

---

## 5. Design 2: host workspace-ops channel (S40 → W-S41) for fingerprints, checks, git ops and repo detection

### 5.1 Why a new channel, not the session shell or the fs frames

| Option | Pros | Blocking cons |
|---|---|---|
| Session shell endpoint (`routes_resources.py:3257` → `runner/app.py:8296`) | Exists; sandboxed by `os_env`; owner-only | Needs a live runner and a session with `os_env`. No sessionless use: native fingerprints at handoff, merges, setup before a session exists, detached check checkouts. Synchronous HTTP over the runner tunnel. 120 s default timeout. Runs inside the *agent's* session environment, which the agent could have altered (env, PATH shims). |
| Add ops to `host.fs_request` / `host.fs_write_request` | No new frame kind; old hosts fail fast on unknown ops | Unguarded against the orphan reaper (`connect.py:6027-6034`). Results shaped like runner payloads. Read/write split. 20 s proxy default (`_host_filesystem.py:30`). No job model for minute-long commands. |
| **New `host.workspace_op` channel** (recommended) | Purpose-built: job ids, capability token, reaper-guarded, sandboxable, sessionless | One more frame family (M) |

**Verdict.** Build **W-S41**. Keep the session shell as a **fallback** for hosts that lack `CAP_WORKSPACE_OPS` while a step runner is alive. Mark checks run that way as "agent-environment" in evidence.

### 5.2 Wire design (mirrors the worktree frames)

- **Frames** in `omnigent/host/frames.py`:
  - `HostWorkspaceOpFrame{request_id, op, root, params, timeout_s, op_key}` (`host.workspace_op`).
  - `HostWorkspaceOpResultFrame{request_id, status: ok|failed|running, payload, error, error_code}`.
  - Unsolicited host-to-server `HostWorkspaceJobEventFrame{job_id, op_key, state, payload}`. Precedent: `host.harness_login_completed`, `frames.py:248, 1009`.
  - Capability token `CAP_WORKSPACE_OPS = "workspace_ops:1"` in `HOST_CAPABILITIES` (`frames.py:94-109`).
- **Host.** Add a dispatcher branch beside `HostCreateWorktreeFrame` (`connect.py:6017-6026`). Each op runs under `_run_host_subprocess_in_thread` (`connect.py:1611-1630`). The handler table is a **registry** loaded from an entry point (`omnigent.host.workspace_ops`), so Coral's git and exec logic lives in `coral/host_ops/` and the upstream diff stays at framing and dispatch only (**W-S42**).
- **Server.**
  - New `omnigent/server/routes/_host_workspace_ops.py`, a copy of the `_await_host_worktree_result` pattern (`_host_worktree.py:131-187`).
  - `HostConnection.pending_workspace_ops` (`host_registry.py:506-561` pattern), failed on disconnect (`host_registry.py:100-191` pattern).
  - Result routing in `host_tunnel.py`, after the pattern at 999-1000.
  - Job events go to a Coral callback that writes `coral_signals`.
- **Engine side** (`coral/omni/host_ops.py`): request-free calls, as `fire.py` makes them, using `deps.host_registry.get(host_id)`. In a sharded deployment, effects are claimed only by the replica whose local registry holds the host tunnel (R-W7).

### 5.3 Op catalog (v1)

All mutating git ops refuse refs outside `refs/heads/coral/` and `refs/coral/`. All paths are confined under `root`. All ops carry `op_key` for idempotency. The host checks postconditions first: for example, a merge whose agent head is already an ancestor of HEAD returns `already_applied`.

| Op | Params | Result | Used by |
|---|---|---|---|
| `probe` | — | `{is_git, main_root, head, branch, traits:{submodules, lfs, lfs_installed, sparse, shallow}, git_version}` | Binding creation, run start |
| `head` | — | `{head, branch, merge_in_progress}` | E2 when W-S47 is absent |
| `fingerprint` | `level: "L1"/"L2"`, `exclude: [...]` | `{level, digest, head, branch, dirty_count, untracked_count, duration_ms}` | Evidence, handoff, read-only violation detection |
| `diff_paths` | `from, to?, pathspecs` | `{changes:[{path,status}], truncated}` | Test-integrity rule |
| `commit_all` | `message, trailers{}, author?` | `{commit, empty}` | E10 |
| `merge` | `ref, no_ff, message, leave_conflicts` | `{status: clean/conflict/already_applied, merge_commit?, conflicts[]}` | E11 and conflict prep |
| `abort_merge` | — | `{}` | Recovery |
| `salvage` | `ref` | `{commit or null}` | Restart |
| `reset_to` | `commit, clean: "fd"` | `{}` | Restart |
| `branch` | `action: create/delete, name, at?` | `{}` | Cleanup |
| `fetch` / `push` | `remote, refspec, force_with_lease?` | `{ok, stderr_tail}` | Checkpoints (sandboxes) |
| `worktree.add_detached` | `commit, path?` | `{worktree_path}` | Coral-controlled checkout (if W-S47 is not taken) |
| `files.copy_include` | `from_root, patterns` | `{copied[]}` | Setup |
| `files.materialize` | `files:[{path, content_b64}]` (capped) | `{written[]}` | EGM scoped inputs, templates |
| `coral_file.write` | `rel_path` (must be under `.coral/`), `content`, `expected_sha256` or `must_not_exist` | `{sha256, git_status}` | Editor save (section 6) |
| `exec.start` | `argv` or `shell`, `cwd_rel`, `env_allow[]`, `timeout_s`, `max_output`, `sandbox: {profile}`, `reports: [globs]` | `{job_id, state: running}` | Coral-run checks, setup |
| `exec.status` / `exec.cancel` | `job_id` | `{state, exit_code, timed_out, duration_ms, stdout_tail, stderr_tail, reports:[{path, content_b64, truncated}]}` | Polling and recovery |
| `folder.snapshot` / `folder.restore` / `folder.fingerprint` | `binding` | as above | Plain folders |

**Exec semantics.**

- **Sandboxing.** Run through `create_os_environment(...)` with a Coral-chosen `OSEnvSpec` and sandbox (`create_os_environment` `os_env.py:1114+`; `_HelperProcessClient` `os_env.py:402+`). This gives the same bwrap/seatbelt write roots and `egress_rules` as agent tools. If no sandbox backend is available, fall back to unsandboxed, labelled `"unsandboxed"` in evidence.
- **Environment.** Only the `os_env` defaults plus `env_allow` (`datamodel.py:735-752` describes `env_passthrough`).
- **Process control.** Run as its own process group, killed on cancel or timeout.
- **Job journal.** `data_dir()/coral/jobs/<job_id>.json` holds state and result, so a reconnect or server restart can recover by `exec.status`.
- **Concurrency.** A host-side semaphore, default 2.
- **Output caps.** Tails of 64 KiB each. Report files are capped at 2 MiB total per job. The server-side WebSocket max message size is **UNVERIFIED**; the host client accepts 100 MiB (`connect.py:5309`). Large artifacts go to the artifact store through the server.

**Coral-controlled checkout** (deep dive §9.3 item 3). `worktree.add_detached` at the step's result commit, then `git checkout <base_commit> -- <protected test paths>` in that checkout, then `exec` with the pinned command. Remove the checkout afterwards. This needs no session and no runner.

### 5.4 Fingerprint algorithm

- **L2 (exact, git).** `cp $(git rev-parse --git-path index) $tmp`; `GIT_INDEX_FILE=$tmp git add -A -- . ':(exclude).coral/runtime/**'`; `GIT_INDEX_FILE=$tmp git write-tree`. The result is a tree SHA over tracked files plus untracked-but-not-ignored files, which matches Draft 4 §6.1's definition. Copying the real index keeps the stat cache, so only changed files are hashed.
  - Caveat: it writes loose objects for changed files, which `gc` reclaims later. Very large generated files that are not ignored inflate the cost; report `duration_ms` and warn above a threshold.
- **L1 (cheap, per command).** `sha256(HEAD ‖ git status --porcelain=v2 -z --untracked-files=all ‖ (path,size,mtime_ns) of each dirty path)`.
  - Reuse `GitFilesystemRegistry`'s porcelain conventions, but **not its `_SKIP_DIRS` filtering** (`filesystem_registry.py:1280-1340`): evidence must follow `.gitignore` exactly, not a UI skip list.
  - L1 equality means "unchanged" with high probability. A difference means "changed".
- **Evidence rule** (deep dive §9.2): a command counts if `L1_before(cmd) == L1_at_submit` and the submit-time L2 equals the L2 recorded for that L1 state. Store both levels in `coral_command_observations`.
- **Plain folders.** Same algorithm against the shadow repo (section 4.4).

### 5.5 Where each mode computes and reports observations

| Mode | Compute | Transport | Seam |
|---|---|---|---|
| `claude-sdk` | Runner, around `_execute_os_env_tool`: L1 before for `sys_os_shell`, L1 after for shell, write and edit. The hook point is next to `tool_dispatch.py:7297`. | Add an `observations` field to the runner `/mcp/execute` response (`mcp_routes.py:375`). The server MCP handler hands it to the Coral intercept at TOOL_RESULT (`orchestration.py:13239-13258`), which records the observation synchronously before the result returns to the model. Correlation: `(session_id, operation_id or rpc_id)` plus `sha256(tool, canonical args, output)`, joined to transcript items by digest (call-id availability **UNVERIFIED**). | W-S43, W-S44a |
| `codex` | Harness adapter: L1 at `ToolCallRequest` for internally executed items, L1 at `ToolCallComplete` (`_executor_adapter.py:1106-1125, 1150-1185`). Add `exit_code` to `ToolCallComplete.metadata` in `_codex_builtin_tool_completion` (`codex_executor.py:2836-2883`). Whether the adapter knows the cwd: **UNVERIFIED**; otherwise use the item's `cwd`, which Codex sends (`codex_executor.py:2797-2800`). | On-disk outbox, as `SessionPrRegistry` does → runner reporter → new `external_workspace_observations` session event (`common.py:165`, `routes_events.py:2931` pattern) → Coral signal. | W-S43, W-S44b |
| `claude-native` / `codex-native` | Runner relay `/hook/observe-tool`: generalize `file_change_observer` (`bridge.py:8234-8248`; `runner/app.py:5406`) into an observer list and compute L1 after. **Hints only** (1 s curl). | Same outbox and event. | W-S43, W-S44b |
| All | Engine at `submit_handoff` and hand-back: **W-S41 `fingerprint L2`** is authoritative. | Synchronous host op. | W-S41 |

### 5.6 Repository command detection (Draft 4 §6.1, §6.2; deep dive §9.4)

**Reuse `host.fs_request list_or_read`** to fetch `package.json`, `pyproject.toml`, `justfile`, `Makefile`, `tox.ini`, `noxfile.py`, `Cargo.toml`, `go.mod`, `.pre-commit-config.yaml` and `.github/workflows/*.yml`. Parse them server-side in `coral/evidence/detect.py`. Write proposals to `coral_repo_command_patterns`. The author confirms them.

Nuance: `list_or_read` reads the **main work tree's current checkout**. To detect from the base ref, use the run worktree (after E1) or a later `git show <ref>:<path>` op. No new host op is needed for v1.

### 5.7 Security model

- The server authorizes the owner: host owner is the run owner, as in `hosts.py:1673-1683`. The host trusts its server, as it already does for worktree frames that take arbitrary `repo_path`.
- Host-side guards:
  - argv-only git;
  - ref-prefix confinement;
  - path confinement under `root`, using the `_resolve_workspace_path` semantics in `workspace_fs.py`;
  - `.coral/` confinement for `coral_file.write`;
  - `exec` sandboxed when possible;
  - no credential env passthrough by default.
- Commands come from confirmed workflow or repo files. The workflow version pins the exact command string (section 6), and changes to `.coral/**` inside a run are an integrity violation.

---

## 6. Design 3: workflow-file storage and the read/write path

### 6.1 Options

| Option | Fit with Draft 4 | Problems |
|---|---|---|
| A. Repo file only (`.coral/workflows/*.yaml`) | §12 "YAML file in `.coral/workflows/`"; §3 "Sharing: Git repositories" | Host must be online to edit or run. Runs would race edits. |
| B. Server DB only | Simple | Contradicts §12 and §3. No git sharing or review. |
| **C. Repo canonical + DB versions and drafts** (recommended) | §7.6 "workflow versions" table; §7.7 runs pin versions | More moving parts |

### 6.2 Recommended design (C)

- **Canonical source:** `<repo>/.coral/workflows/<key>.yaml`, plus the layout file `<key>.layout.json` keyed by stable node ids (deep dive §14.4), plus `<repo>/.coral/repo.yaml` (setup and checks, section 4.7).
- **DB (`coral_*`):**
  - `coral_repo_bindings` (owner, host, root);
  - `coral_workflow_sources` (`binding_id`, `rel_path`, `last_sha256`, `last_git_status`, `last_read_at`);
  - `coral_workflow_drafts` (unsaved or offline edits: `base_sha256`, `content` capped or as an artifact ref);
  - `coral_workflow_versions` (immutable, from deep dive §7.2, with `source_ref` = binding, path, `head` and dirty flag).
- **Read path.** `GET /v1/coral/bindings/{id}/workflows` calls `read_workspace_from_host(op="list_or_read", workspace=<root>, session_id="coral:<binding>", params={"path": ".coral/workflows", "limit": 1000})` (`_host_filesystem.py:59-139`). Per file, `params={"path": ".coral/workflows/<key>.yaml"}`. **Reuse.**
- **Write path.** `PUT /v1/coral/bindings/{id}/workflows/{key}` with `{content, base_sha256}` calls the `coral_file.write` host op (W-S41, or W-S50 as an fs-write op).
  - The write is atomic (temp file plus rename) under a precondition.
  - On mismatch it returns 409 with the current content, and the editor runs a 3-way merge UI.
  - With the host offline, it saves a draft (`coral_workflow_drafts`), and the UI shows "not yet saved to repo".
- **Run start.** Read the file (or the draft, if the user chooses), validate it, and snapshot it as a `coral_workflow_versions` row with content hash and `source_ref`. The run pins that version. Agents editing `.coral/**` in run worktrees do not affect the run. The engine also flags such edits through `diff_paths` for evidence integrity. **Rules team:** deny `sys_os_write`/`edit` under `.coral/` for run-owned sessions.
- **Managed sandboxes.** A run in a sandbox takes its version from the DB. The sandbox clone's `.coral/` is irrelevant. Authoring against a sleeping sandbox is not supported; author locally or through drafts.
- **Templates.** Ship them in the `coral` package (server-side). "Use template" writes into the repo through `coral_file.write`, or into a draft.
- **CLI path** (optional, phase 1): `omnigent coral workflow push <file>` posts content to `POST /v1/coral/workflow-versions`, so phase 1 (engine core and Simulate) needs no host ops at all.

### 6.3 Endpoints (all under `create_app(extra_routers=…)`, deep dive S32)

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/v1/coral/bindings` | Create from `(host_id, path)`. Server calls W-S41 `probe`. Owner-only. |
| GET | `/v1/coral/bindings/{id}/workflows` | Listing through `list_or_read`. Merges in drafts. |
| GET | `/v1/coral/bindings/{id}/workflows/{key}` | Returns `{content, sha256, git_status, draft?}`. |
| PUT | `/v1/coral/bindings/{id}/workflows/{key}` | `{content, base_sha256}` → 200 `{sha256}`, 409 conflict, or 202 draft-saved when the host is offline. |
| GET/PUT | `/v1/coral/bindings/{id}/workflows/{key}/layout` | Same mechanics. |
| GET/PUT | `/v1/coral/bindings/{id}/repo-config` | `.coral/repo.yaml`. |
| POST | `/v1/coral/bindings/{id}/detect-commands` | Section 5.6. |
| POST | `/v1/coral/workflow-versions` | Phase 1 CLI/API upload. |

Errors reuse the Omnigent mapping: host absent → `host_absent_error` (409 or `WRONG_REPLICA`) (`_host_launch.py:177-212`); host lacks the capability → 409 "update omnigent host".

---

## 7. Design 4: long-wait survival (gates waiting days, long steps)

### 7.1 What happens today (verified)

| Situation | Local external host | Managed sandbox |
|---|---|---|
| Step agent working for hours (turn in flight) | Protected: SDK reaper skips in-flight (`process_manager.py:1597-1603`), runner watchdog checks `has_active_work` (`runner/app.py:1616-1652`), pane reaper checks busy (`pane_reaper.py:257-275`) | Same, and `keep_warm` is true while busy (`busy_check.py:64-75`) |
| Gate waiting days (engine-held; step sessions idle) | Harness process, pane and runner are reaped after about 1 h. The session stays resumable, and the next message relaunches (`routes_resources.py:2514-2530` shows the reconnect ladder for writes). Engine state lives in the DB. **OK.** | Runner exits after `keep_warm_s`, so there are no pongs and no `touch`, and the provider suspends or reaps the sandbox. Resume-capable providers keep the volume. **Non-resumable providers lose the workspace on relaunch** (`managed_hosts.py:4062-4078`). |
| Pending in-turn approval (Omnigent elicitation) | Keeps the runner alive (`pending_approvals.has_any_pending`, `runner/app.py:1627`) | Keeps it warm |
| Engine-held gate (S6 server-side elicitation) | Not in runner `pending_approvals`, so it does not pin the runner. That is the desired behaviour locally. | Sandbox may sleep (see above) |
| Coral-run check through a host op | Host daemon is long-lived. OK. | **Invisible to keep-warm** (runner-keyed, `managed_host_keepalive.py:230-276`). The sandbox can suspend mid-check. |
| Laptop closed | Mid-turn sessions are held for 72 h (`orchestration.py:8638`). Roots are relaunched on return; children are not (`app.py:4273`). | n/a |
| Sub-agent native panes | Capped at a 1 h idle window even if the session window is longer (`pane_reaper.py:140-152`). This matters if step sessions are children (deep dive §8.2). | same |

### 7.2 Mitigations

1. **Engine pause semantics.** Treat host offline, sandbox asleep or runner reaped as `paused:infrastructure` (Draft 4 §7.8), not as failure. The reconciler re-checks host presence through `host_registry.get` and DB liveness, and resumes by sending the next brief or nudge. That message triggers Omnigent's relaunch.
2. **Children are not relaunched by Omnigent.** If step sessions are children, the engine must relaunch them or restart the slot from its last handoff, as F24 says.
3. **Checkpoint pushes** for sandbox runs at every accepted handoff (section 4.8, Stage B). Make it a workflow or run setting, on by default for non-resumable providers. The validator warns when a sandbox run has no push credentials (UNVERIFIED for non-GitHub forges).
4. **Keep-warm lease (W-S45).** Add `managed_host_keepalive.hold(host_id, until, reason)` / `release(...)`, consulted in a host-keyed refresh path that does not need a runner. The engine holds a lease:
   - while a W-S41 job is running on a sandbox host;
   - optionally while a gate is open, for at most `gate_keep_warm_s`, a per-run setting with default 0, because of cost.
5. **Long-step reaper exemptions (S27 → W-S51)** only if the phase 4 retests fail. Proposed shape: a session label `coral.keep_alive=1` consulted by the pane reaper's `is_busy` and the process manager's skip set. **Not recommended now.**
6. **Server restart during waits.** Durable `coral_*` state and gate rows (deep dive §6/§7). Host jobs recover through `exec.status(job_id)` against the host journal.

---

## 8. New seams (Omnigent file changes)

| ID | Seam | Location | Size | Phase | Upstream candidate |
|---|---|---|---|---|---|
| W-S41 | Host workspace-op channel: frames + capability token + host dispatcher branch (reaper-guarded) + server proxy + pending map + tunnel routing + job event frame | `omnigent/host/frames.py:94-109, 213-279` (+ dataclasses/decoders); `omnigent/host/connect.py:6017-6034` (dispatcher), `1611-1630` (guard); new `omnigent/server/routes/_host_workspace_ops.py` (pattern `_host_worktree.py:131-187`); `omnigent/server/host_registry.py:506-561`; `omnigent/server/routes/host_tunnel.py:999-1000` | M | 3 (fingerprint-only slice can land in 2) | Maybe (generic) |
| W-S42 | Workspace-op handler registry via entry point, so Coral's ops live in `coral/host_ops/` | `omnigent/host/connect.py` (new small registry module) | XS | 3 | Yes |
| W-S43 | Tool-completion observer registry: one registry called where `pr_observer` is called today, with optional *before* hooks and `exit_code` metadata | `omnigent/runner/tool_dispatch.py:7297-7307`; `omnigent/runtime/harnesses/_executor_adapter.py:1106-1125, 1150-1185`; `omnigent/harnesses/claude_native/bridge.py:8233-8250`; `omnigent/runner/app.py:5406-5440`; `omnigent/tools/mcp.py:717-726`; `omnigent/inner/codex_executor.py:2836-2883` | S | 3 | Yes |
| W-S44 | Observation transport: (a) runner `/mcp/execute` response field plus a server intercept hook at TOOL_RESULT; (b) `external_workspace_observations` event type with outbox reporter | `omnigent/runner/mcp_routes.py:375`; `omnigent/server/routes/_sessions/orchestration.py:13239-13258`; `omnigent/server/routes/_sessions/common.py:165, 595-612`; `omnigent/server/routes/sessions/routes_events.py:2931`; pattern `omnigent/runner/pr_reports.py` | S | 3 | Partly |
| W-S45 | Host-keyed keep-warm lease for managed sandboxes | `omnigent/server/managed_host_keepalive.py:176-276` | S | 3 (sandbox phase) | Yes |
| W-S46 | Guard `fs_request`/`fs_write` handlers against the orphan reaper (bug fix) | `omnigent/host/connect.py:6027-6034` (wrap in `_run_host_subprocess_in_thread`) | XS | 1-2 | Yes |
| W-S47 | `create_worktree` extensions: return `head_commit`; `detached` + `commit` mode; optional `worktree_parent` | `omnigent/host/git_worktree.py:419-448, 493-508, 655-708`; `frames.py:692-743`; `_host_worktree.py:112-128, 190-257` | S | 2-3 | Yes |
| W-S48 | Skip session-delete/archive worktree cleanup for `coral.*`-labelled sessions (only if run sessions carry `git_branch`) | `omnigent/server/routes/sessions/routes_events.py:4166-4189`; `helpers.py:10294` | XS | 2 | No |
| W-S49 | Managed-sandbox worktrees and relaunch from a checkpoint branch (refines S28) | `omnigent/server/schemas.py:2011-2013`; `managed_hosts.py:353-366, 4062-4078` | S/M | later | Yes |
| W-S50 | `coral_file.write` op, if not folded into W-S41: one branch in `_dispatch_fs_write_op` | `omnigent/host/connect.py:4449-4557`; `_host_filesystem.py:142-226` | XS | 5 | No |
| W-S51 | Per-session reaper exemption label (only if S27 retests fail) | `pane_reaper.py:160-275`; `process_manager.py:1591-1603`; `runner/app.py:1616-1652` | S | 4 | Maybe |

S40 maps to W-S41 + W-S42 + W-S43 + W-S44. S28 maps to W-S49. S27 maps to a retest, plus W-S51 only if the retest fails.

---

## 9. Data model additions (Coral lineage; follow deep dive §7.1 conventions)

| Table | Key columns | Purpose |
|---|---|---|
| `coral_repo_bindings` | `id`, `user_id`, `host_id`, `repo_root` (canonical main work tree), `display_name`, `default_base_ref`, `traits` (CompressedText), `project_id?` | Workspace anchors (git or plain folder: `kind`) |
| `coral_repo_command_patterns` | `id`, `binding_id`, `kind` (test/lint/format/custom), `pattern`, `source` (`package.json#scripts.test`…), `confirmed_by`, `confirmed_at` | Section 5.6 |
| `coral_workspaces` | `id`, `run_id`, `slot_id?`, `kind` (run/agent/check/folder), `host_id`, `worktree_path`, `branch`, `base_ref`, `root_sha256`, `status` (creating/ready/removing/removed/lost), `created_at`, `removed_at` | Lifecycle (section 4) |
| `coral_workspace_marks` | `id`, `workspace_id`, `activation_id`, `kind` (start/handoff/merge/salvage), `commit`, `l2_digest`, `l1_digest` | Restart safety and evidence anchors |
| `coral_host_jobs` | `id` (= job_id), `run_id`, `host_id`, `op`, `op_key` (unique), `state`, `exit_code`, `result_ref`, `lease_expires_at` | Checks and setup job tracking (feeds `coral_effects`) |
| `coral_workflow_sources` / `coral_workflow_drafts` | as in section 6.2 | File binding and offline drafts |
| `coral_command_observations` (deep dive §7.2) | add `fp_level`, `fp_before_l1`, `fp_after_l1`, `fp_l2?`, `source` (runner_shell/sdk/native_hook/engine), `correlation_digest` | Section 5.4/5.5 |

---

## 10. Risks (workspace area)

| ID | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| R-W1 | Orphan reaper steals subprocess exit statuses on unguarded host paths, so a failed check reads as exit 0 | Plausible / critical for evidence | W-S46. All W-S41 ops guarded. A test that runs a failing command under the reaper (`tests/host/test_orphan_reaper.py` pattern). |
| R-W2 | Sandboxed agents cannot commit in linked worktrees (git common dir outside write roots) | Unknown / medium | Engine-owned commits (section 4.3). Phase 2 probe. |
| R-W3 | Children's per-session workspace on a shared runner is accidental, not supported (`orchestration.py:12072-12082` unvalidated) | Unknown / high for topology | Contract test before choosing the children topology. Otherwise step sessions are root/sibling sessions bound with `host_id` (validated). |
| R-W4 | User deletes a run session with "delete branch" and destroys a Coral branch | Medium / high | Section 4.6 (no `git_branch`) or W-S48. |
| R-W5 | Managed sandbox sleeps mid-check or mid-gate; non-resumable relaunch loses work | High on modal/e2b / high | W-S45 lease, checkpoint pushes, W-S49. |
| R-W6 | Host/server version skew: an older host ignores new frames and the server times out | High for user-run hosts / medium | `CAP_WORKSPACE_OPS` gating. The validator blocks runs on incapable hosts with "update host". |
| R-W7 | Sharded deployments: the engine worker on the wrong replica cannot reach the host tunnel (`_host_launch.py:161-212`) | Low for local-first / high for hosted | Claim-if-local effect dispatch, or route through the replica that owns the host. |
| R-W8 | Worktree sprawl (repeat-for-each × roster) fills the disk and slows `git worktree list` | Medium / medium | Caps, immediate post-merge removal, retention sweeps. |
| R-W9 | Fingerprint cost on huge repos (untracked scans, LFS) | Medium / medium | L1 per command, L2 only at evaluation points. Report `duration_ms`. `core.untrackedCache`/fsmonitor where configured. |
| R-W10 | Agents escape the worktree (nested worktrees, `cd ..`, editing `.coral/`) | Medium / high | Sandbox write roots, policies (rules team), HEAD/branch check in `fingerprint`, `.coral/` integrity diff. |
| R-W11 | Restart reset destroys valuable partial work or user take-over edits | Medium / medium | Salvage refs and the take-over guard (section 4.4). |
| R-W12 | Submodules and LFS produce broken worktrees | Medium / medium | `probe`, then refuse or require setup (section 4.5 item 5). |
| R-W13 | Missing upstream design docs (`SESSION_GIT_WORKTREE.md`, `SESSION_WORKSPACE_SELECTION.md`) make intent hard to confirm | — | Treat code as the spec. Add contract tests in `tests/coral/omni/`. |

---

## 11. Tests: nearest existing suites to extend and new ones

Follow `tests/README.md` and `tests/_helpers/README.md`, and keep input matrices at the lowest layer (repo CLAUDE.md). The real-host primitive is `isolated_host` in `tests/_helpers/host.py` (`tests/_helpers/README.md:21, 67-87`).

| Layer | Existing file (pattern) | Add |
|---|---|---|
| Host git ops (real git in tmp) | `tests/host/test_git_worktree.py` (fixture `git_repo` at l.132; 30+ cases 150-725) | `head_commit` returned; `detached` mode; branch scheme D/F safety (`coral/r-x/base` + `coral/r-x/a-…`); merge clean, conflict and abort; salvage + reset preserves ignored files; L1/L2 fingerprints (ignored excluded, untracked included, idempotent, staged vs unstaged equal); submodule and LFS probe |
| Frames | `tests/host/test_frames.py:2016-2255` (worktree), `2613-2661` (fs) | Round trips and decode errors for the workspace-op frames, the job event frame and the capability token |
| Host handlers | `tests/host/test_connect.py` (fs/worktree handler tests); `tests/host/test_orphan_reaper.py:99-180` | Handler success, failure and crash replies; **exit status preserved under the reaper** for W-S41 and W-S46; job journal recovery after cancel |
| Server proxies | `tests/server/routes/test_host_worktree.py:131-412`; `tests/server/routes/test_host_filesystem.py:104-189` | Proxy success, failure, timeout, disconnect and capability-absent paths |
| Request-free creation | `tests/server/scheduled/test_fire.py` | Coral facade create/rollback mirrors |
| Session binding | `tests/server/integration/test_session_worktree_create.py` | Sessions bound to Coral worktrees without `git`; **child session with its own workspace on a shared runner (R-W3 contract test)** |
| Observers | `tests/runner/test_pr_observer_isolation.py`; `tests/runner/test_native_file_observer.py`; `tests/native/test_tool_observer_hook.py`; `tests/inner/test_codex_executor.py` | Observer registry ordering and isolation; Codex `exit_code` metadata; outbox reporter retry/ack (mirror the `pr_reports` tests) |
| Reapers (S27 retest) | `tests/runner/test_runner_idle_active_work.py`; `tests/runner/test_busy_check.py:10-52`; `tests/runner/test_runner_entry.py`; `tests/terminals/test_pane_reaper.py`; `tests/runtime/test_process_manager.py` | Long in-flight turn survives; idle step after a gate resumes on the next brief; sub-agent pane cap |
| Sandboxes | `tests/server/test_managed_host_keepalive.py:55-172`; `tests/server/test_managed_hosts.py` | Host-keyed lease refresh without a runner; relaunch from a checkpoint branch |
| Egress | `tests/inner/egress/`; `tests/test_codex_egress.py` | Only if the rules team relies on new cases |
| New | `tests/coral/workspace/` (lifecycle state machine with a fake host-ops client), `tests/coral/evidence/test_fingerprint_rules.py`, `tests/stores/coral/test_workspace_store.py` | Fault injection: crash between commit and merge; duplicate `op_key`; host disconnect mid-job |

---

## 12. Open questions

1. **Topology:** children of the orchestrator, or root/sibling sessions? It depends on the R-W3 contract test. My recommendation for code-changing slots is root sessions with a validated `host_id` + `workspace` bind until children are proven.
2. Do engine commits on `coral/*` branches run repo hooks? (Recommendation: no; record it.)
3. When agents merge parallel code changes, are Coral-run checks **mandatory** on the merged result? (Recommendation: yes by default; section 4.5 item 4.)
4. Where do worktrees live by default: Omnigent's sibling `<repo>-worktrees/` or a Coral root under `~/.omnigent/coral/`?
5. Default `gate_keep_warm_s` for sandbox runs (cost vs latency), and whether checkpoint pushes need explicit user consent (they push branches to the user's remote).
6. Coral-run checks: always sandboxed? What is the fallback when bwrap or seatbelt is unavailable (macOS without seatbelt, or Linux containers without user namespaces; bwrap availability inside managed sandboxes is **UNVERIFIED**)?
7. Is `tool_use_id` available server-side for `claude-sdk` MCP calls, for exact correlation? (**UNVERIFIED**.)
8. Can a session with `host_type="external"` bind to a managed host id (Stage A of section 4.8)? (**UNVERIFIED**.)
9. Plain-folder workspaces with several writers: unsupported in v1?
10. Engine-initiated PR creation at run end: reuse agent steps (polly-style), or add a host op over `pr_resource`? `HostFsWriteFrame` has no PR-create op (`frames.py:1177-1214`).

---

## 13. Work packages for the roadmap (dependency-ordered)

| WP | Title | Depends on | Phase | Seams |
|---|---|---|---|---|
| WS-01 | Orphan-reaper guard for host fs handlers (bug fix + test) | — | 1 | W-S46 |
| WS-02 | `coral_repo_bindings` + binding API. Before W-S41 exists, validate a binding with `list_worktrees_on_host`, which raises on non-git paths, plus `list_or_read`; `probe` arrives with WS-08 | Engine store scaffolding (S29-S31) | 1-2 | — |
| WS-03 | Workflow versions via API/CLI upload (no host) | Engine core | 1 | — |
| WS-04 | `coral.omni.worktrees` facade: request-free create/remove/list, ownership labels, rollback (fire.py pattern) | WS-02 | 2 | — |
| WS-05 | `create_worktree` extensions (head commit, detached, parent dir) | — | 2 | W-S47 |
| WS-06 | Run worktree lifecycle E1-E6 for single-writer steps; session binding without `git` | WS-04, WS-05, session facade (S3/S4) | 2 | — |
| WS-07 | R-W3 contract test (child workspace on shared runner) → topology decision | — | 2 | — |
| WS-08 | Host workspace-op channel + registry (frames, proxy, guard, capability token, job journal) | WS-01 | 3 (fingerprint slice earlier) | W-S41, W-S42 |
| WS-09 | Fingerprint L1/L2 (git + plain folder) host ops | WS-08 | 3 | — |
| WS-10 | Observer registry + transports for claude-sdk, codex and native | WS-09 | 3 | W-S43, W-S44 |
| WS-11 | Engine-owned commits, salvage/reset restart safety | WS-08 | 3 | — |
| WS-12 | Exec jobs + Coral-run checks (run worktree + Coral-controlled detached checkout), JUnit reports | WS-08, WS-05 | 3 | — |
| WS-13 | Repo command detection (`list_or_read` parsers) + confirmation API | WS-02 | 3 | — |
| WS-14 | Per-worktree setup (`.coral/repo.yaml`, `.worktreeinclude` fallback) | WS-12 | 3 | — |
| WS-15 | Agent worktrees + serial merge + conflict-resolution protocol | WS-11, WS-12 | 3 (merge) / 6 (parallel steps) | — |
| WS-16 | Workflow file read/write endpoints + drafts + version snapshot at run start | WS-02, WS-08 (write op) | 5 | W-S50 or W-S41 op |
| WS-17 | S27 reaper retests (no code unless they fail) | WS-06 | 4 | (W-S51) |
| WS-18 | Managed sandbox: keep-warm lease, checkpoint push, worktrees in sandbox, relaunch from checkpoint | WS-08, WS-11 | later | W-S45, W-S49 |
| WS-19 | Session-delete protection (only if run sessions carry `git_branch`) | WS-06 | 2 | (W-S48) |
| WS-20 | EGM scoped input workspaces (`files.materialize` + `create_dir`) | WS-08 | 6 | — |

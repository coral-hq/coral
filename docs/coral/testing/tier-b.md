# Tier B: the real claude-sdk harness against a mock model

Tier B tests run the real `ClaudeSDKExecutor` and the real `claude` CLI with
`tests/server/integration/mock_llm_server.py` as the only model endpoint. They
live in `tests/e2e/coral/`. The walking-skeleton proofs among them, and the live
proxy's unit test (`test_live_proxy.py`), run in CI in the `coral-e2e` group (below). The other Tier B files run only locally: the
inherited `E2E Tests` workflow is disabled on this fork. Run them all locally
with:

```bash
uv run --no-sync pytest tests/e2e/coral --reruns 0 -rs -n 2 --dist=loadscope
```

Each test that starts the CLI skips when `claude` is not on `PATH`;
`test_live_proxy.py` and `test_claude_sdk_kit.py` need no CLI. The walking-skeleton tests
(`test_skeleton.py`, `test_runner_loss.py`, `test_sandbox_probe.py`) fail
instead when `CORAL_E2E_REQUIRE_CLI=1` is set, as the lane sets it. The stack
sample also skips unless `CORAL_TIER_B_STACK_SAMPLE=1` is set (see below), and
the live variant unless `CORAL_E2E_LIVE=1` and `ANTHROPIC_API_KEY` are set.

## The `coral-e2e` lane

`.github/scripts/ci/python-matrix.json` has a `coral-e2e` group in the
`pytest` job of `.github/workflows/ci.yml`. It runs, on two workers with
`--dist=load`:

- `tests/e2e/coral/test_live_proxy.py`: the live proxy's unit tests, with a
  fake upstream and a fake key;
- `tests/e2e/coral/test_skeleton.py`: the review loop end to end, and the server
  SIGKILL proofs;
- `tests/e2e/coral/test_runner_loss.py`: a lost runner, a lost host and a step
  retry;
- `tests/e2e/coral/test_sandbox_probe.py`: ADR-05's probe 15 on a single-user,
  an allow-listed-token and an accounts server, and the test that binds the gate
  label's table to the probe's pins.

Explicit paths override `addopts`'s `--ignore=tests/e2e` (`pyproject.toml`). The proxy's file comes
first so that `--dist=load` spreads the stack tests over both workers; the
order is meant to keep the two longest tests apart.
`tests/coral/test_ci_lane.py` pins the row, that the lane collects every proof
and the proxy's unit tests, and that it installs the CLI from the in-repo
action. The job's steps for this group:

- Node 22, then `claude` from `./.github/actions/setup-harness-cli`
  (`harness: claude`): version 2.1.295 from its `manifest.json`, installed from
  a lockfile with sha512 integrity. The version goes into the job summary.
- `bubblewrap` and `kernel.apparmor_restrict_unprivileged_userns=0`, as for
  every group, so the claude-sdk OS sandbox is Linux bwrap.
- `OMNIGENT_TEST_TIMEOUT_SCALE=4`, `CORAL_E2E_REQUIRE_CLI=1`, `--timeout=300`,
  `ANTHROPIC_API_KEY` unset, and `artifacts/` uploaded even on failure (probe
  15 writes its verdicts there). The job runs pytest with `--showlocals`, so
  the tests' own frames hold canaries and tokens only in redacted `Secret`s;
  the stack helpers' frames hold the raw per-run values, so only a failure in
  a stack's start or teardown can print them. The accounts stack keeps its
  cookie secret, admin password and owner JWT in `Secret`s and drops the frames
  of a failed sign-in, which
  `test_a_stack_that_fails_to_start_shows_none_of_its_secrets` checks. Its
  checkout does not set `persist-credentials: false`, as for every `pytest` group
  (CRL-160).

Budgets: each test's absolute deadlines stay within 240 s (the default-lease
proof within 360 s, under `timeout(420, method="signal")`), and the group
within 15 minutes with its setup. Measured locally the CI way on macOS: the
row in about 265 s; the default-lease proof about 188 s, the host outage about
130 s, the SIGKILL proof about 36 s, the retry about 21 s, the happy path about
18 s, the runner kill about 13 s, probe 15 about 11 s and the allow-listed-token
test about 9 s. The identity probe, added later, takes about 13 s in a plain
local run; the row was not timed again. A test that cannot meet its budget
moves to a lower layer, not to a nightly lane.

## The walking-skeleton stack

`tests/e2e/coral/_skeleton.py` holds the mechanics. Each helper takes its
inputs from the caller; faults and assertions stay in the tests.

- `skeleton_stack(root, *, mock_url, host_config, host_env, ...)` starts a
  server subprocess with the Coral plugin (`server_runner`, a fixed port and
  database across restarts), a host daemon with an isolated home
  (`isolated_host`) and a temporary git repository, all under the stack's
  root, and waits for the host online and `GET /v1/coral/info`. The server
  removes the allow-listed runner token unless `allowlisted_token` is given.
- Every stack gets a private short harness socket root,
  `mkdtemp(dir="/tmp", prefix="crl-")` (`OMNIGENT_HARNESS_TMP_PARENT`, under the
  AF_UNIX path limit), and its own `TMPDIR` (`prefix="crl-t-"`), both removed
  with the stack. No recipe sets `OMNIGENT_HARNESS_TMP_PARENT` by hand.
- `minimal_env()` is the base environment, with no credential: `PATH` with
  python, git, `claude` and `node` and the system directories, the locale
  names and `TMPDIR` (the stack then gives its own), and
  `DISABLE_AUTOUPDATER=1` and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. The
  happy path asserts both switches reach the step's live CLI.
- At exit, a SIGTERM included, no process the stack started may survive: the
  stack fails if a server, host, runner, CLI or tool process of it is left.
- `start_server(skeleton)` restarts the server after a test's
  `server.kill(); server.wait()`; `respawn_host(skeleton)` restarts the host
  daemon from its first launch's own argv, environment and working directory,
  so it reuses the same home and identity (`isolated_host` refuses an existing
  identity).
- `runner_pid(skeleton, session_id)` reads the host's launch line for the
  session's current runner and asserts the pid leads its group.
- `wait_for(fn, *, deadline, what)` waits to an absolute deadline. Its failure
  adds the run's detail, `claude --version` and, for a mock stack only, the
  server, host and runner log tails.
- Every E2E test uses `timeout(<n>, method="signal")` with deadlines summing
  below it: the default `thread` method `os._exit`s and skips teardown.
- `make_repo` presets `core.untrackedCache=true`. A runner's first start in a
  repository otherwise probes the untracked cache for about 6 s, and a
  scripted turn that ends inside that window looks like a drift (CRL-161).

**Scripting the steps.** One isolated mock per test. Each step's queue is keyed
by a unique token in its goal, the reviewer's longer, with `required_tools` so
the CLI's side requests cannot drain it. Each step's first call is held until
its brief arrives, so the test reads the activation id from the brief instead
of predicting it. Calls are told apart by the brief's activation line, the
`runner_lost` nudge after a relaunch, and the salvage paragraph of a retried
step's brief. No scripted report carries a token.

**Held calls and the CLI's watchdog.** The claude CLI abandons a model call
that gets no response headers for about 120 s and sends it again (measured with
CLI 2.1.325; the lane runs 2.1.295). A test that holds a call longer must hold
the repeat too and release both; the default-lease proof does, and checks that
the two held calls carry the same body.

**Runner-loss faults.** A runner-loss test captures the runner's process tree
(its group and every descendant) before the fault, runs the fault only when
the tree holds the step's `claude` and at least two group members, and then
waits until the group and the captured tree have ended before it releases the
mock (`group_tree`, `group_tree_ended`). On Linux the CLI is a descendant, not
a group member: bwrap's `--new-session` gives it its own session, and it ends
through bwrap's die-with-parent after the group sweep.

**The proofs and what each crosses.** Each E2E crosses a process boundary the
lower layers cannot: a server SIGKILL, host git ops, host-launched runners and
their process trees.

| Test | Fault | What it shows |
|---|---|---|
| `test_skeleton.py::test_the_review_loop_runs_end_to_end_on_a_real_stack` | none | implementer → evidence check (refused, then accepted) → read-only reviewer (a write refused, one `changes_requested` pass) → gate (an unknown outcome refused, then approved) → completed run whose checkout command works; one session per slot activation, each briefed once; no drift pause; no refused runner event |
| `test_skeleton.py::test_the_review_loop_survives_server_sigkills_mid_step_and_at_the_gate` | server SIGKILL with a model call held, then at the open gate; 10 s lease | the same runner reconnects and its handoff is accepted; the gate's visit id, token and prompt id are unchanged and it is answered once; zero duplicate sessions; no `runner_lost` |
| `test_skeleton.py::test_a_runner_reconnecting_after_a_default_lease_restart_is_not_relaunched` | the runner's group `SIGSTOP`ped, server SIGKILL, restart with the production lease and grace, `SIGCONT` 20 s after the new leader's first liveness pass | no `runner_lost`, no wake row, the same runner id |
| `test_runner_loss.py::test_a_killed_step_runner_is_relaunched_in_the_same_session` | `killpg` of the step runner | one loss, one wake `relaunched`, the same session and generation, a new runner id; the run never pauses |
| `test_runner_loss.py::test_an_offline_host_holds_the_step_and_its_return_relaunches_it` | host daemon SIGKILL; 30 s grace | the hold (`infra` / `infra.host_offline`, Cancel only, `:resume` and `:retry` 409), then `respawn_host`, the hold ends and the same session is relaunched as one loss |
| `test_runner_loss.py::test_retrying_a_blocked_step_fences_salvages_resets_and_briefs_a_new_session` | a blocked handoff, then `:retry` | paused `recovery.restarting` until the restart finished; the old session closed and its tree gone; one salvage ref holding the old attempt's file; a reset worktree; generation 2 in a new session whose brief names the ref |
| `test_sandbox_probe.py` (three stack tests) | none | ADR-05's probe 15 verdicts, pinned per platform: on a single-user server, on one that keeps the allow-listed runner token, and on an accounts server, where the same probe first runs outside the sandbox and must open every owner path |

The review loop is a test fixture, `tests/e2e/coral/fixtures/review_loop.yaml`
("Implement with review loop": implement, review with a `changes_requested`
back arrow, an approval gate). The packaged template and Simulate are
CRL-157.

**Probe 15's choreography.** The implementer's first call and the reviewer's
calls are held, and the mock releases only the oldest held call, so the test
releases one call at a time and orders the holds until the implementer's probe
call is the oldest. The host-side controls then run, the probe call is
released, its result is read from the mock's ledger, the controls run again
with the reviewer still held, and only then is the reviewer let go. Every
target needs a host-side control; a target that went missing fails as a failed
control, never as a verdict. Without pins for the platform, each stack test
writes `artifacts/probe15-<platform>.json` (and
`artifacts/probe15-token-<platform>.json` or
`artifacts/probe15-identity-<platform>.json`) when `artifacts/` exists, as in CI, and fails "not pinned"; pins are taken from
those files, with every open verdict given its owner ticket. They hold verdict
tokens and the recorded versions only.

**The identity probe's choreography.**
`test_probe_15_on_a_server_that_requires_identity` starts the stack with
`skeleton_stack(identity=True)`: an accounts server with a throwaway cookie
secret and first admin, the owner's JWT from `POST /auth/login` stored in the
host's `~/.omnigent/auth_tokens.json` before the host starts, and the stack's
client sending that JWT. The host spawns runners directly
(`OMNIGENT_RUNNER_ZYGOTE=0`), so the test first checks, by name only, that the
implementer's runner holds its binding token and the host's bearer. It plants
a cookie-secret canary in the host's home and opens throwaway listeners for
other programs' services. With both steps' first calls held, it reads the run's
`gate_integrity` and runs the same probe outside any sandbox in the step's
worktree; that run must open every owner path, or the test fails as a broken
probe. Then the step runs the probe, its controls run again, and the run must
complete. The verdicts, the outside verdicts and the recorded versions are
written before any assertion, so a failing lane run still leaves them.

**Pinning probe 15.** The macOS pins come from local runs; the Linux pins come
from the `coral-e2e` lane's artifacts (`pytest-coral-e2e-<run id>`). The lane
runs for a non-draft pull request, or a push to `main`, `development` or a
release branch. For each failure in `test_sandbox_probe.py`:

- A failed control, a broken probe, a count of `claude` CLIs or a timeout is
  rerun, never re-pinned.
- "Moved from its pins": re-pin only a move between closed verdicts (such as
  `hidden` and `denied`), the socket, TCP and plant checks with their owners,
  and the single-user `owner_bare` checks with the accepted residual.
- Any open verdict on a credential path is escalated to a person and a ticket,
  never re-pinned: a `.read` other than `denied` or `hidden`; `minted`,
  `mismatch`, `refused` or `not_present` on `mint`, `bearer` or `stored`;
  `reachable` on an environment or the cookie secret; a bare owner request on
  the accounts server other than `refused`; or any `shell_env_names.names`
  other than `none`.
- A person checks every pin copied from the lane, and the comment above the
  pins names the lane run. A move that changes a policy row's open owners also
  needs a new sandbox policy revision and rows (ADR-05, "Addendum: CRL-159
  probe 15 on identity-requiring servers"); the binding test fails until they
  exist.

## The live variant

`test_skeleton.py::test_live_review_loop_survives_server_sigkills` runs the
review loop against the real Anthropic API, with a server SIGKILL while the
implementer's session runs and another at the open gate. It skips unless
`CORAL_E2E_LIVE=1` and `ANTHROPIC_API_KEY` are set; `CORAL_E2E_LIVE_MODEL`, if
set, becomes the host's `ANTHROPIC_MODEL`. Export the key in your own shell,
then:

```bash
just coral e2e-live
```

The recipe runs that one test with `--reruns 0 -rs --no-showlocals`. **Run it
only on a machine with no other users.** It is kept collectible, so the lane
collects it and it skips there; no lane runs it with a key.

**Where the key goes** (`tests/e2e/coral/_live_proxy.py`). The fixture reads
the key once into a `Secret` whose repr is redacted, removes it from the test's
environment, and starts a proxy inside the test process on `127.0.0.1`. The
host's `auth:` is `{type: api_key, api_key: <per-run token>, base_url:
<proxy>}`, so the host and every CLI it starts get a random
`secrets.token_urlsafe(32)` token, never the key. The proxy:

- admits only that token, as `x-api-key` or else as a bearer token (the
  runner's model listing sends one), compared in constant time, else 401;
- forwards only `POST /v1/messages` and `GET /v1/models`, else 404, to
  `https://api.anthropic.com` alone, with certificate checks on and no
  redirects followed, sending the key as `x-api-key` and neither token header;
- caps request bodies at 1 MiB and upstream calls at 4 at once, refuses a body
  cut short, writes no TLS key log, and logs nothing itself;
- closes at teardown and cuts any connection still open.

Its unit tests, which run in the lane, cover each refusal
(`tests/e2e/coral/test_live_proxy.py`), and
`test_a_failing_live_run_shows_its_key_nowhere_in_the_report` checks that a
failing live run's report, with `-l --tb=long`, never shows a fake key. Live
failures carry no log tails. At teardown the test asserts that no file under
its basetemp holds the key, reporting a count only, then deletes the basetemp.

**What the token does not fence.** The token reaches the CLI's command line
(its `--settings` key helper), which any local account can read, and the
stack's server serves unauthenticated local requests. So while a live run
lasts, another account on the machine could read the token and spend through
the proxy. There is no spend cap. No process the test starts is given the key,
but the key is not confined to the test process: removing it from the test's
environment does not scrub the initial environment block of pytest, or of the
shell and tools that started it, which another process of the same user outside
the sandbox can read (CRL-167). A step's shell cannot read it directly: on macOS
27.2.1 since CRL-165 (S111, probe 15; no CI lane runs macOS, CRL-170), and on
Linux because of pid namespaces. On a single-user server, though, a step can
act as the owner, an accepted residual (ADR-05, "Addendum: CRL-159 probe 15 on
identity-requiring servers"). The proxy path is the claude-sdk gateway path (it
sets a base URL), so a host with only `ANTHROPIC_API_KEY` and no base URL is not
exercised.

## The harness is claude-sdk

The claude-sdk probe in `docs/coral/decisions/probes/SPK-03-claude-sdk.md`
showed that the CLI sends every model call to the mock when
`ANTHROPIC_BASE_URL` points at it.
`CORAL_TIER_B_HARNESS = "claude-sdk"` in `tests/e2e/coral/conftest.py` records
that choice. The test-only openai-agents fallback is not needed.

Give the CLI the mock root URL, for example `http://127.0.0.1:5123`, with no
`/v1` suffix. `register_inline_agent(..., mock_llm_base_url=mock_llm_server_url)`
passes the root form. `register_dir_agent_with_mock_llm` builds a URL that ends
in `/v1`, so do not use it for claude-sdk agents.

## Check for proxied HTTP(S) egress

`test_tier_b_executor.py` drives the executor directly, so it controls the CLI
environment. `mock_only_env` in `tests/e2e/coral/_claude_sdk_kit.py` takes the
inherited environment and returns changes that:

- Unset every name outside a short allowlist (`PATH`, `LANG`, `LC_ALL`, `LC_CTYPE`, `TERM`,
  `TMPDIR`, `USER`, `LOGNAME`, `SHELL`, and `PYTEST_*` and coverage names).
  Credentials such as `CLAUDE_CODE_OAUTH_TOKEN`, provider switches such as
  `CLAUDE_CODE_USE_BEDROCK`, and `AWS_*` names never reach the CLI.
- Set `HOME` and `CLAUDE_CONFIG_DIR` to a fresh directory from
  `write_claude_home`, whose `.claude.json` declares the stdio probe MCP server
  `probe`.
- Set `ANTHROPIC_BASE_URL` to the mock root URL, and
  `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`. The executor gets its key from
  `api_key_helper="printf %s mock-key"`.
- Set `HTTPS_PROXY`, `HTTP_PROXY` and `ALL_PROXY` in both cases to an
  `EgressRecorder`, and `NO_PROXY` and `no_proxy` to `127.0.0.1,localhost`. An
  inherited `no_proxy=*` therefore cannot route around the recorder.

`test_claude_sdk_kit.py` checks that result against an environment full of
credentials and proxy overrides.

`EgressRecorder` is a local proxy that answers every request with `403` and
records its request line. The main test asserts that the recorder saw nothing
after a full turn with a tool call. The recorder sees only clients that honor
the proxy variables. It does not see raw sockets, DNS, or child processes that
ignore those variables, so the test proves no proxied HTTP(S) egress, not that
nothing left the machine. The control test,
`test_egress_recorder_sees_model_traffic_aimed_off_the_machine`, sets
`ANTHROPIC_BASE_URL=https://api.example.invalid` and asserts that the recorder
logs `CONNECT api.example.invalid:443 HTTP/1.1`. Without that control, an empty
recorder could also mean the CLI ignores proxy settings.

`test_tier_b_sample.py` runs a session through the real server and runner. The
shared session-scoped `live_server` fixture in `tests/e2e/conftest.py` starts
the runner with this process's environment and real `HOME`. The runner's CLI
can therefore read your `~/.claude` settings, hooks, MCP servers and login, and
the test cannot install the recorder. The sample skips unless you opt in. Run
it only where no Claude login or provider credential exists, such as a clean CI
runner or container:

```bash
CORAL_TIER_B_STACK_SAMPLE=1 uv run --no-sync pytest tests/e2e/coral/test_tier_b_sample.py --reruns 0 -rs
```

It relies on the agent's mock base URL, the `mock-key` credential and the
mock's request ledger.

## Keep the scripted queues for the turn under test

Claude Code's auto-mode classifier sends its own `/v1/messages` calls through
the same base URL for some model ids. In one probe it added 10 calls to a
three-call turn and drew from the test's queue. A drained queue answers
`Mock LLM response`, which fails the token assertions. Follow these rules:

- At executor level, use `permission_mode="bypassPermissions"`. The classifier
  does not run in that mode.
- At stack level, key the queue by a unique model id and pass
  `required_tools=[<the tool the turn calls>]`, so requests that do not
  advertise that tool cannot consume it. Add the title queue and send the
  `x-omnigent-background-session-titles: off` header, as
  `test_tier_b_sample.py` does.
- Route executor-level queues with `match=<unique token>` on an
  `isolated_mock_llm_server_url`, and add a few spare `done` entries for CLI
  side requests that repeat the prompt.

The CLI hides connector MCP tools behind `ToolSearch`. Script
`tool_search_then_call(tool, arguments, call_id=...)`, which answers
`ToolSearch` with `select:<tool>` and then calls the tool. Omnigent tools
(`mcp__omnigent__*`) need no search step.

The stack sample sets `os_env.sandbox.type: none`. The OS sandbox is not under
test, and macOS seatbelt refuses a virtualenv outside the agent's working
directory.

## Old pinned runners skip

`pytest_collection_modifyitems` in `tests/e2e/coral/conftest.py` adds
`min_runner_version("0.22.0")` to every item under `tests/e2e/coral/` and to no
other item. The autouse `_enforce_min_runner_version` fixture in
`tests/e2e/conftest.py` then skips those tests when
`OMNIGENT_COMPAT_RUNNER_VERSION` names an older runner:

```bash
OMNIGENT_COMPAT_RUNNER_VERSION=0.21.0 uv run --no-sync pytest tests/e2e/coral --reruns 0 -rs
```

Each test reports `requires runner >= 0.22.0; running 0.21.0`. Without the
opt-in, the stack sample reports its opt-in reason instead. The stack
sample also carries `compat_smoke`, so the compat PR gate selects it with
`-m compat_smoke`.

The version is a heuristic. 0.22.0 is the first version line that carries
Coral. An upstream 0.22.0 tag without Coral would not skip. The real guard is
the `coral_runner:2` token, which a host with Coral installed advertises in its
hello; the Tier B gate does not check it yet.

## What Tier B cannot prove yet

Every model call is scripted, so Tier B does not show real model behaviour
(following a brief, choosing tools and handoff labels, how often a reviewer
loops), the direct API-key path without a gateway, real error texts and
retries for 401, 429, 529 and overloaded answers (CRL-156), real streaming
latency against the CLI's own watchdogs, or real spend. The kills land only
while the CLI waits for a model answer: none lands while an MCP call to the
server is in flight (the handoff's own POST included) or while a step's
session is being created or briefed. Every kill restarts the only server, so a
leader change between live replicas is covered in process only
(`tests/coral/omni/test_recovery.py`).

- TOOL_CALL policy on connector MCP tools. The probe showed that
  `_can_use_tool_gate` is not called in `auto` or `bypassPermissions`. In
  `auto` the outcome depends on the CLI's classifier, not on Omnigent policy. A
  Tier B test can therefore not show a DENY holding for those tools.
- This is a product-level gap, not only a test limit. In the default `auto`
  configuration, an Omnigent TOOL_CALL DENY on a connector MCP tool is not
  enforced. A planned gate on a `PreToolUse` hook fixes it. Until then, run
  connector-heavy sessions in `default` permission mode, where the DENY holds.
  `mcp__omnigent__*` tools are gated on the server and are not affected.
- The timeout on in-process `mcp__omnigent__*` tool calls. The probe measured
  only stdio connector tools.
- The missing-token case and the assertion that an unpinned host advertises
  `coral_runner:2`. Neither is written yet.

## Add a Tier B test

1. Put the test in `tests/e2e/coral/`. The version gate applies by itself.
2. Call `skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)` first.
3. For an executor-level test, use `isolated_mock_llm_server_url`,
   `write_claude_home`, `mock_only_env` with an `EgressRecorder`, and
   `make_executor(..., permission_mode="bypassPermissions")`. Pass
   `inherited=os.environ` to `mock_only_env`. Assert that
   `recorder.request_lines` is empty.
4. For a stack-level test, use `http_client`, `live_runner_id` and
   `mock_llm_server_url` with the queue guards above.
5. Assert on what the turn produced: the final text, the marker file, or the
   `tool_result` that `tool_results(get_mock_message_requests(...), call_id=...)`
   finds in the mock's ledger.

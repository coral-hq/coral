# Tier B: the real claude-sdk harness against a mock model

Tier B tests run the real `ClaudeSDKExecutor` and the real `claude` CLI with
`tests/server/integration/mock_llm_server.py` as the only model endpoint. They
live in `tests/e2e/coral/` and run in the e2e gate. Run them locally with:

```bash
uv run --no-sync pytest tests/e2e/coral --reruns 0 -rs -n 2 --dist=loadscope
```

Each test skips when `claude` is not on `PATH`.

## The harness is claude-sdk

Spike 4 passed (`docs/coral/decisions/probes/SPK-03-claude-sdk.md`): the CLI
sends every model call to the mock when `ANTHROPIC_BASE_URL` points at it.
`CORAL_TIER_B_HARNESS = "claude-sdk"` in `tests/e2e/coral/conftest.py` records
that choice. The test-only openai-agents fallback is not needed.

Give the CLI the mock root URL, for example `http://127.0.0.1:5123`, with no
`/v1` suffix. `register_inline_agent(..., mock_llm_base_url=mock_llm_server_url)`
passes the root form. `register_dir_agent_with_mock_llm` builds a URL that ends
in `/v1`, so do not use it for claude-sdk agents.

## Prove that no call left the machine

`test_tier_b_executor.py` drives the executor directly, so it controls the CLI
environment. `mock_only_env` in `tests/e2e/coral/_claude_sdk_kit.py` sets:

- `HOME` to a fresh directory from `write_claude_home`, whose `.claude.json`
  declares the stdio probe MCP server `probe`.
- `ANTHROPIC_BASE_URL` to the mock root URL, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`.
- `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `CLAUDE_CONFIG_DIR` unset. The
  executor gets its key from `api_key_helper="printf %s mock-key"`.
- `HTTPS_PROXY` and `HTTP_PROXY` to an `EgressRecorder`, with
  `NO_PROXY=127.0.0.1,localhost`.

`EgressRecorder` is a local proxy that answers every request with `403` and
records its request line. The main test asserts that the recorder saw nothing
after a full turn with a tool call. The control test,
`test_egress_recorder_sees_model_traffic_aimed_off_the_machine`, sets
`ANTHROPIC_BASE_URL=https://api.example.invalid` and asserts that the recorder
logs `CONNECT api.example.invalid:443 HTTP/1.1`. Without that control, an empty
recorder could also mean the CLI ignores proxy settings.

`test_tier_b_sample.py` runs a session through the real server and runner. The
session-scoped `live_server` fixture owns the runner environment, so this test
cannot install the recorder. It relies on the agent's mock base URL, the
`mock-key` credential and the mock's request ledger instead.

## Keep the scripted queues for the turn under test

Claude Code's auto-mode classifier sends its own `/v1/messages` calls through
the same base URL for some model ids. In spike 1 it added 10 calls to a
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

Each test reports `requires runner >= 0.22.0; running 0.21.0`. The stack
sample also carries `compat_smoke`, so the compat PR gate selects it with
`-m compat_smoke`.

The version is a heuristic. 0.22.0 is the first version line that carries
Coral, and the compat jobs pin older tags today. An upstream 0.22.0 tag
without Coral would not skip. The real guard is a runner that advertises the
`coral_runner:1` token, which arrives with TLS-01.

## What Tier B cannot prove yet

- TOOL_CALL policy on connector MCP tools. Spike 1 showed that
  `_can_use_tool_gate` is not called under `bypassPermissions`, and not called
  in `auto` when the auto-mode classifier allows the call. A Tier B test can
  therefore not show a DENY holding for those tools. The fix is S21, a gate on
  a `PreToolUse` hook, owned by HRN-02. `mcp__omnigent__*` tools are gated on
  the server and are not affected.
- The timeout on in-process `mcp__omnigent__*` tool calls. Spike 7 measured
  only stdio connector tools.
- The missing-token case and the assertion that an unpinned runner advertises
  `coral_runner:1`. Both wait for TLS-01.

## Add a Tier B test

1. Put the test in `tests/e2e/coral/`. The version gate applies by itself.
2. Call `skip_if_harness_cli_missing(CORAL_TIER_B_HARNESS)` first.
3. For an executor-level test, use `isolated_mock_llm_server_url`,
   `write_claude_home`, `mock_only_env` with an `EgressRecorder`, and
   `make_executor(..., permission_mode="bypassPermissions")`. Assert that
   `recorder.request_lines` is empty.
4. For a stack-level test, use `http_client`, `live_runner_id` and
   `mock_llm_server_url` with the queue guards above.
5. Assert on what the turn produced: the final text, the marker file, or the
   `tool_result` that `tool_results(get_mock_message_requests(...), call_id=...)`
   finds in the mock's ledger.

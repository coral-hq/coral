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
| `dev/lint/custom_lint.py` | S39 | coral-specific | Registers the `coral-import-boundary` rule last in `RULES` (S39). |
| `dev/lint/lint_coral_import_boundary.py` | S39 | coral-specific | Added. Enforces Coral's pure/omni/db/app/root three-tier import boundaries (S39). |
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
| `omnigent/db/utils.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
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
| `omnigent/host/connect.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/service.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/host/service_entry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/_acp_omnigent_mcp.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/inner/claude_sdk_executor.py` | S95, S13 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Under the Coral credential flag, refuses a turn before the CLI starts when there is no API key helper or gateway, or when `os_env` has no available bwrap or seatbelt sandbox, and strips subscription tokens from the CLI env (S13). |
| `omnigent/inner/claude_sdk_harness.py` | S13 | coral-specific | Reads `HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL` into the executor (S13). |
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
| `omnigent/runner/app.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
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
| `omnigent/runtime/workflow.py` | S95, S13 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Sets `HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL=1` for claude-sdk specs with `params.coral` (S13). |
| `omnigent/server/app.py` | S95, S32 | upstream-extension | Wires `server_plugins` loading, router mounting ahead of `_SPAStaticFiles`, policy-module merging, and lifespan hook execution (S32). Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/server_plugins.py` | S32 | upstream-extension | Added. Defines `ServerServices`, `ServerPluginRegistration`, `load_server_plugins`, and `enter_lifespan_hooks` (S32). |
| `omnigent/server/mcp_compatibility.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/performance_metrics.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_session_harness_readiness.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_sessions/common.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_sessions/helpers.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/_sessions/orchestration.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/auth.py` | S92, S95 | coral-specific | The CLI login consent page now says "A Coral client", "this Coral server" and "from Coral", and its title suffix is "— Coral"; the upgrade notice, the omnigent login text and the server messages stay as they were (S92) Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/routes/device_auth.py` | S92 | coral-specific | The device-grant consent page now says "this Coral server" and its title is "Authorize access — Coral"; env var names, protocol headers and client ids stay as they were (S92) |
| `omnigent/server/routes/sessions/routes_permissions.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/server/static/api_only_landing.html` | S92 | coral-specific | On the API-only landing page the title and heading name Coral, and the Details link points to the coral-hq/coral README; the OMNIGENT_SKIP_WEB_UI mentions and the uv cache clean omnigent command stay as they were (S92) |
| `omnigent/session_import/local.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/__init__.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/_omnigent_compat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/spec/omnigent.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/telemetry/client.py` | S98 | coral-specific | Telemetry is always disabled: Coral sends no usage telemetry to Omnigent's service. |
| `omnigent/tools/builtins/async_inbox.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/browser.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/spawn.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/builtins/ui.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/tools/manager.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `omnigent/util/tmux_compat.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `openapi.json` | S95 | coral-specific | Regenerated: the title and API descriptions follow the S95 brand transform. |
| `pnpm-lock.yaml` | S83 | coral-specific | Locks `@fontsource-variable/newsreader` 5.3.0 (S83). |
| `pyproject.toml` | S29, S39b, S39c | coral-specific | Points `coral` at `coral.cli:main`, includes `coral*` and Coral package data (S29); adds `"coral"` to isort `known-first-party` (S39b) and `[tool.coverage.run].source` (S39c). |
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
| `tests/host/test_local_server.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/inner/test_claude_sdk_executor.py` | S95, S13 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. Adds the Coral credential and sandbox refusal tests, with the non-Coral regression (S13). |
| `tests/inner/test_claude_sdk_harness.py` | S13 | coral-specific | Adds the Coral credential flag threading test (S13). |
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
| `tests/runner/test_runner_entry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runtime/harnesses/test_executor_adapter.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/runtime/test_claude_sdk_spawn_env.py` | S13 | coral-specific | Adds the Coral credential flag tests for Coral and non-Coral specs (S13). |
| `tests/runtime/test_filesystem_registry.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/scripts/test_dependency_ci.py` | S39d | coral-specific | Asserts the `coral` matrix group collects `tests/coral` and `misc` ignores it (S39d). |
| `tests/scripts/test_security_gate.py` | S99 | coral-specific | Expects the gate and scan to fetch their trust rules from the default branch. |
| `tests/server/integration/test_kiro_permission_delivery.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_lifespan.py` | S98 | coral-specific | Expects the server never to start the telemetry client, in CI or not. |
| `tests/server/integration/test_oidc_cli_ticket_hijack_e2e.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_session_create_harness_readiness.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/integration/test_sessions_compact.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/routes/test_session_resources.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/routes/test_sessions_upload_limits.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_admin_list.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_app.py` | S32 | upstream-extension | Adds server-plugin loading, failure abort, lifespan ordering, bundle policy registration, and `/v1/coral/info` gate tests (S32). |
| `tests/server/test_oidc_cli_ticket.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
| `tests/server/test_runner_session_init.py` | S95 | coral-specific | Brand transform (S95): user-visible "Omnigent" text in its strings and CLI help says Coral. |
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

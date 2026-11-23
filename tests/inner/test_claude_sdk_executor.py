# CORAL(S95): user-visible "Omnigent" text changed to "Coral" by .coral/tools/rebrand.py
"""Tests for ClaudeSDKExecutor."""

import asyncio
import base64
import json
import logging
import os
import shutil  # CORAL(S116)
import subprocess  # CORAL(S116)
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from omnigent.inner.claude_sdk_executor import (
    _remove_orphaned_temp_dirs,  # CORAL(S116)
    _to_anthropic_content_blocks,
)
from omnigent.inner.executor import (
    ExecutorConfig,
    ExecutorError,
    TextChunk,
    ToolCallComplete,
    ToolCallRequest,
    ToolCallStatus,
    TurnComplete,
)


# CORAL(S116): tests leave the shared temp dir alone; a test of the sweep itself restores it
@pytest.fixture(autouse=True)
def _no_shared_temp_dir_sweep(monkeypatch):
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._remove_orphaned_temp_dirs", lambda: None
    )


class _SDKClient:
    """Quiet SDK lifecycle; scenarios override the interactions they exercise."""

    def __init__(self, options):
        self.options = options

    async def connect(self):
        return None

    async def query(self, prompt, session_id="default"):
        return None

    async def disconnect(self):
        return None


def _sdk_types():
    """Fresh stand-in message types and option container for one scenario."""

    class SDKTypes:
        AssistantMessage = type("AssistantMessage", (), {})
        UserMessage = type("UserMessage", (), {})
        SystemMessage = type("SystemMessage", (), {})
        ResultMessage = type("ResultMessage", (), {})
        StreamEvent = type("StreamEvent", (), {})

        class ClaudeAgentOptions:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

    return SDKTypes


class _SDKTools:
    """MCP tool metadata exposed by the scripted SDK."""

    @staticmethod
    def tool(name, desc, params):
        def decorator(handler):
            return type(
                "Tool",
                (),
                {"name": name, "description": desc, "parameters": params, "handler": handler},
            )()

        return decorator

    @staticmethod
    def create_sdk_mcp_server(**kwargs):
        return kwargs


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ---------------------------------------------------------------------------
# Tests: Prompt extraction
# ---------------------------------------------------------------------------


class TestPromptExtraction(unittest.TestCase):
    def _make_executor(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        return ClaudeSDKExecutor()

    def test_resumed_session_uses_last_user_message(self):
        executor = self._make_executor()
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "Second question"},
        ]
        self.assertEqual(
            executor._build_prompt(messages, resume_session=True),
            "Second question",
        )

    def test_tool_history_replays_only_into_a_fresh_session(self):
        executor = self._make_executor()
        messages = [
            {"role": "user", "content": "Weather in SF?"},
            {"role": "tool_call", "content": {"tool": "weather", "args": {"city": "SF"}}},
            {"role": "tool_result", "content": "SF: 61F"},
            {"role": "assistant", "content": "61F."},
            {"role": "user", "content": "Warmer than NYC?"},
            {"role": "tool_call", "content": {"tool": "weather", "args": {"city": "NYC"}}},
        ]
        self.assertTrue(executor.replays_tool_history())
        fresh = executor._build_prompt(messages, resume_session=False)
        self.assertIn('tool call: {"tool": "weather", "args": {"city": "SF"}}', fresh)
        self.assertIn("tool result: SF: 61F", fresh)
        self.assertIn('tool call: {"tool": "weather", "args": {"city": "NYC"}}', fresh)
        self.assertEqual(fresh.count("Warmer than NYC?"), 1)
        self.assertEqual(executor._build_prompt(messages, resume_session=True), "Warmer than NYC?")

    def test_resumed_session_includes_all_trailing_user_messages(self):
        """Batched buffered steers: all trailing user messages must reach the SDK.

        When the runner collapses several buffered steered messages into one
        continuation turn, history ends in >1 consecutive user message the SDK
        has never seen. Sending only the last silently drops the earlier ones
        (the two-steer "second message ignored" bug). All trailing user
        messages must be concatenated into the prompt.
        """
        executor = self._make_executor()
        messages = [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer"},
            {"role": "user", "content": "steer one"},
            {"role": "user", "content": "steer two"},
        ]
        prompt = executor._build_prompt(messages, resume_session=True)
        self.assertIn("steer one", prompt)
        self.assertIn("steer two", prompt)
        # Prior turns are SDK-cached on resume — not replayed.
        self.assertNotIn("First question", prompt)

    def test_resumed_session_compact_is_a_separate_prompt(self):
        executor = self._make_executor()
        for compact_content in (
            "/compact",
            [{"type": "text", "text": "/compact"}],
            [{"type": "input_text", "text": "/compact"}],
        ):
            with self.subTest(content=compact_content):
                # The runner dispatches pending input before the compact control.
                messages = [
                    {"role": "user", "content": "previous input"},
                    {"role": "user", "content": compact_content},
                ]
                compact_prompt = executor._build_prompt(messages, resume_session=True)
                self.assertEqual(compact_prompt, "/compact")
                messages.extend(
                    [
                        {"role": "user", "content": "next input"},
                        {"role": "user", "content": "another queued input"},
                    ]
                )
                self.assertEqual(
                    executor._build_prompt(messages, resume_session=True),
                    "next input\n\nanother queued input",
                )

    def test_resumed_session_rejects_non_object_content_blocks(self):
        with self.assertRaisesRegex(ValueError, "Anthropic content blocks must be objects"):
            self._make_executor()._build_prompt(
                [{"role": "user", "content": ["/compact"]}], resume_session=True
            )

    def test_resumed_session_trailing_run_stops_at_assistant(self):
        """Only the trailing run of user messages (after the last non-user) is sent."""
        executor = self._make_executor()
        messages = [
            {"role": "user", "content": "old one"},
            {"role": "user", "content": "old two"},
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "new one"},
            {"role": "user", "content": "new two"},
        ]
        prompt = executor._build_prompt(messages, resume_session=True)
        self.assertIn("new one", prompt)
        self.assertIn("new two", prompt)
        self.assertNotIn("old one", prompt)
        self.assertNotIn("old two", prompt)

    def test_resumed_session_multimodal_trailing_run_preserves_blocks(self):
        """A multimodal message in the trailing run keeps structured blocks for all."""
        executor = self._make_executor()
        messages = [
            {"role": "assistant", "content": "answer"},
            {"role": "user", "content": "describe this"},
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,aGVsbG8=",
                    },
                    {"type": "input_text", "text": "and this too"},
                ],
            },
        ]
        prompt = executor._build_prompt(messages, resume_session=True)
        self.assertIsInstance(prompt, list)
        types = [b.get("type") for b in prompt]
        self.assertIn("image", types)
        joined = " ".join(b.get("text", "") for b in prompt if b.get("type") == "text")
        self.assertIn("describe this", joined)
        self.assertIn("and this too", joined)

    def test_empty_messages(self):
        executor = self._make_executor()
        self.assertEqual(executor._build_prompt([], resume_session=False), "")

    def test_no_user_messages(self):
        executor = self._make_executor()
        messages = [{"role": "assistant", "content": "Hello"}]
        self.assertEqual(executor._build_prompt(messages, resume_session=False), "")

    def test_dict_content_converted(self):
        executor = self._make_executor()
        messages = [{"role": "user", "content": {"key": "value"}}]
        self.assertIn("key", executor._build_prompt(messages, resume_session=False))

    def test_fresh_session_with_history_serializes_context(self):
        executor = self._make_executor()
        messages = [
            {"role": "user", "content": "The secret codeword is ZEBRA-99."},
            {"role": "assistant", "content": "Understood."},
            {"role": "user", "content": "Summarize our conversation."},
        ]
        prompt = executor._build_prompt(messages, resume_session=False)
        self.assertIn("Conversation so far:", prompt)
        self.assertIn("ZEBRA-99", prompt)
        self.assertIn("Summarize our conversation.", prompt)

    def test_history_unresolved_file_id_becomes_visible_marker(self):
        # A prior-turn attachment the content resolver never inlined must
        # not be serialized as raw block JSON — the model reads that as if
        # the attachment were present and hallucinates its content.
        executor = self._make_executor()
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "file_id": "file_img", "filename": "photo.png"},
                    {"type": "input_text", "text": "look at this image"},
                ],
            },
            {"role": "assistant", "content": "A photo."},
            {"role": "user", "content": "What did I show you?"},
        ]
        prompt = executor._build_prompt(messages, resume_session=False)
        self.assertIn("[Attachment photo.png could not be loaded]", prompt)
        self.assertNotIn("file_id", prompt)
        self.assertIn("look at this image", prompt)

    def _text_of(self, prompt):
        """Join the text blocks of a structured prompt for framing assertions."""
        return "\n".join(block["text"] for block in prompt if block.get("type") == "text")

    def test_cold_reload_replays_historical_image_as_structured_block(self):
        # A restarted/fresh SDK client must be able to *look at* an image from
        # an earlier turn. Flattening it into a text marker leaves the model
        # describing an attachment it cannot see.
        executor = self._make_executor()
        image_payload = base64.b64encode(b"synthetic png bytes").decode("ascii")
        image_data_uri = f"data:image/png;base64,{image_payload}"
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": image_data_uri,
                        "filename": "screenshot.png",
                    },
                    {"type": "input_text", "text": "What is shown here?"},
                ],
            },
            {"role": "assistant", "content": "It shows a test image."},
            {"role": "user", "content": "Summarize our conversation."},
        ]

        prompt = executor._build_prompt(messages, resume_session=False)

        self.assertIsInstance(prompt, list)
        images = [block for block in prompt if block.get("type") == "image"]
        self.assertEqual(len(images), 1)
        self.assertEqual(
            images[0]["source"],
            {"type": "base64", "media_type": "image/png", "data": image_payload},
        )
        # The bytes travel as a structured block, never as prompt text.
        text = self._text_of(prompt)
        self.assertNotIn(image_payload, text)
        self.assertNotIn("data:", text)
        # Framing and ordering survive around the replayed image.
        self.assertIn("Conversation so far:", text)
        self.assertIn("What is shown here?", text)
        self.assertIn("Respond to the latest user message", text)
        self.assertIn("Summarize our conversation.", text)

    def test_cold_reload_replays_historical_file_as_structured_document(self):
        # The same fidelity requirement applies to non-image attachments: a
        # resolved PDF must reach the SDK as a document block, not a marker.
        executor = self._make_executor()
        file_payload = base64.b64encode(b"synthetic pdf bytes").decode("ascii")
        file_data_uri = f"data:application/pdf;base64,{file_payload}"
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "file_data": file_data_uri,
                        "filename": "doc.pdf",
                    },
                    {"type": "input_text", "text": "What does this document say?"},
                ],
            },
            {"role": "assistant", "content": "It is a test document."},
            {"role": "user", "content": "Summarize our conversation."},
        ]

        prompt = executor._build_prompt(messages, resume_session=False)

        self.assertIsInstance(prompt, list)
        documents = [block for block in prompt if block.get("type") == "document"]
        self.assertEqual(len(documents), 1)
        self.assertEqual(
            documents[0]["source"],
            {"type": "base64", "media_type": "application/pdf", "data": file_payload},
        )
        text = self._text_of(prompt)
        self.assertNotIn(file_payload, text)
        self.assertIn("What does this document say?", text)

    def test_cold_reload_keeps_unresolved_history_attachment_visible(self):
        # A resolved and an unresolved attachment in the same history: the
        # resolved one becomes real bytes, the unresolved one must still say
        # so out loud rather than vanish from the structured prompt.
        executor = self._make_executor()
        image_payload = base64.b64encode(b"synthetic png bytes").decode("ascii")
        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": f"data:image/png;base64,{image_payload}",
                        "filename": "resolved.png",
                    },
                    {
                        "type": "input_image",
                        "file_id": "file_missing",
                        "filename": "lost.png",
                    },
                    {"type": "input_text", "text": "two attachments"},
                ],
            },
            {"role": "assistant", "content": "Noted."},
            {"role": "user", "content": "What did I send?"},
        ]

        prompt = executor._build_prompt(messages, resume_session=False)

        self.assertIsInstance(prompt, list)
        self.assertEqual(len([b for b in prompt if b.get("type") == "image"]), 1)
        text = self._text_of(prompt)
        self.assertIn("[Attachment lost.png could not be loaded]", text)
        self.assertNotIn("file_id", text)
        self.assertIn("two attachments", text)

    def test_historical_image_source_block_is_replaced_with_compact_placeholder(self):
        # The ``Read`` tool returns an image file as an Anthropic content block
        # ``{"type": "image", "source": {"type": "base64", ...}}`` — raw base64
        # with no ``data:`` URI prefix. Redaction must catch this shape too, or a
        # replayed image tool result flattens hundreds of KB into prompt text.
        from omnigent.inner.claude_sdk_executor import _render_prior_content_blocks

        image_payload = base64.b64encode(b"synthetic png bytes").decode("ascii")
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_payload,
                },
            }
        ]

        rendered = self._text_of(_render_prior_content_blocks(content))

        self.assertNotIn(image_payload, rendered)
        self.assertIn(
            f"[image: image/png, {len(image_payload)} base64 chars]",
            rendered,
        )


# ---------------------------------------------------------------------------
# Tests: Constructor and properties
# ---------------------------------------------------------------------------


class TestConstructor(unittest.TestCase):
    def test_default_values(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.spec.types import RetryPolicy

        with patch.dict("os.environ"):
            os.environ.pop("OMNIGENT_CLAUDE_CODE_ENTRYPOINT", None)
            executor = ClaudeSDKExecutor()
        self.assertFalse(executor._os_env)
        self.assertIsNone(executor._os_env_spec)
        self.assertIsNone(executor._cwd)
        self.assertIsNone(executor._model_override)
        self.assertEqual(executor._permission_mode, "auto")
        self.assertIsNone(executor._tool_executor)
        self.assertEqual(executor._clients, {})
        self.assertEqual(executor._crashed_sessions, {})
        self.assertFalse(executor._gateway)
        # _extra_env carries Tool Search plus the default RetryPolicy's CLI env.
        self.assertEqual(
            executor._extra_env,
            {
                "ENABLE_TOOL_SEARCH": "true",
                **RetryPolicy().claude_cli.env(),
            },
        )

    def test_os_env_spec_with_no_sandbox_keeps_native_tools_enabled(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

        executor = ClaudeSDKExecutor(
            os_env=OSEnvSpec(
                type="caller_process",
                sandbox=OSEnvSandboxSpec(type="none"),
            )
        )
        self.assertTrue(executor._os_env)
        self.assertIsNotNone(executor._os_env_spec)

    def test_os_env_spec_wraps_cli_and_enables_native_tools(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, PreparedClaudeCli
        from omnigent.inner.datamodel import OSEnvSpec

        spec = OSEnvSpec(type="caller_process", cwd="/tmp/work")
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._find_system_claude",
                return_value="/usr/bin/claude",
            ),
            patch(
                "omnigent.inner.claude_sdk_executor.prepare_claude_cli_path",
                return_value=PreparedClaudeCli(
                    cli_path="/tmp/omnigent-claude-wrapper",
                    enable_native_tools=True,
                ),
            ),
        ):
            executor = ClaudeSDKExecutor(os_env=spec)

        self.assertTrue(executor._os_env)
        self.assertEqual(executor._os_env_spec, spec)
        self.assertEqual(executor._cli_path, "/tmp/omnigent-claude-wrapper")
        self.assertEqual(executor._cwd, "/tmp/work")

    def test_prepare_claude_cli_path_adds_internal_roots_to_read_allowlist(self):
        from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path
        from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
        from omnigent.inner.sandbox import SandboxPolicy

        captured: dict[str, SandboxPolicy] = {}

        def _capture_launcher(_path: str, sandbox: SandboxPolicy) -> str:
            captured["sandbox"] = sandbox
            return "/tmp/launcher"

        spec = OSEnvSpec(
            type="caller_process",
            cwd="/tmp/work",
            sandbox=OSEnvSandboxSpec(
                type="linux_bwrap",
                read_paths=["."],
                write_paths=["."],
                allow_network=True,
            ),
        )

        with (
            patch(
                "omnigent.inner.claude_sdk_executor.resolve_sandbox",
                return_value=SandboxPolicy(
                    backend_type="linux_bwrap",
                    active=True,
                    read_roots=[Path("/tmp/work")],
                    write_roots=[Path("/tmp/work")],
                    write_files=[Path("/dev/null")],
                    allow_network=True,
                ),
            ),
            patch(
                "omnigent.inner.claude_sdk_executor._claude_internal_write_roots",
                return_value=[Path("/home/test/.claude/sessions")],
            ),
            patch(
                "omnigent.inner.claude_sdk_executor._claude_internal_write_files",
                return_value=[],
            ),
            patch(
                "omnigent.inner.claude_sdk_executor.create_exec_launcher",
                side_effect=_capture_launcher,
            ),
        ):
            # CORAL(S115): the shared grants are now an explicit choice
            prepared = prepare_claude_cli_path("/usr/bin/claude", spec, isolate_config=False)

        self.assertEqual(prepared.cli_path, "/tmp/launcher")
        self.assertTrue(prepared.enable_native_tools)
        # Sandbox helpers call ``.resolve(strict=False)``, which on
        # macOS rewrites ``/home`` → ``/System/Volumes/Data/home``.
        # Compare against the resolved form so the assertion is stable
        # across platforms.
        expected = Path("/home/test/.claude/sessions").resolve(strict=False)
        self.assertIn(expected, captured["sandbox"].read_roots)

    def test_default_process_sandbox_wraps_cli_without_enabling_native_tools(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with (
            patch(
                "omnigent.inner.claude_sdk_executor._find_system_claude",
                return_value="/usr/bin/claude",
            ),
            patch(
                "omnigent.inner.claude_sdk_executor.prepare_tight_cli_process_path",
                return_value="/tmp/omnigent-claude-tight-wrapper",
            ),
        ):
            executor = ClaudeSDKExecutor()

        self.assertFalse(executor._os_env)
        self.assertIsNone(executor._os_env_spec)
        self.assertEqual(
            executor._cli_path,
            "/tmp/omnigent-claude-tight-wrapper",
        )

    def test_os_env_spec_without_supported_native_sandbox_disables_native_tools(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, PreparedClaudeCli
        from omnigent.inner.datamodel import OSEnvSpec

        spec = OSEnvSpec(type="caller_process", cwd="/tmp/work")
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._find_system_claude",
                return_value="/usr/bin/claude",
            ),
            patch(
                "omnigent.inner.claude_sdk_executor.prepare_claude_cli_path",
                return_value=PreparedClaudeCli(
                    cli_path="/usr/bin/claude",
                    enable_native_tools=False,
                ),
            ),
        ):
            executor = ClaudeSDKExecutor(os_env=spec)

        self.assertFalse(executor._os_env)
        self.assertEqual(executor._os_env_spec, spec)
        self.assertEqual(executor._cli_path, "/usr/bin/claude")

    def test_model_override(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        executor = ClaudeSDKExecutor(model="claude-haiku-4-5-20251001")
        self.assertEqual(executor._model_override, "claude-haiku-4-5-20251001")

    def test_supports_streaming(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        self.assertTrue(ClaudeSDKExecutor().supports_streaming())

    def test_supports_tool_calling(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        self.assertTrue(ClaudeSDKExecutor().supports_tool_calling())

    def test_databricks_flag_with_profile(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ),
        ):
            executor = ClaudeSDKExecutor(gateway=True)
            self.assertTrue(executor._gateway)
            self.assertEqual(
                executor._extra_env["ANTHROPIC_BASE_URL"],
                "https://example.cloud.databricks.com/ai-gateway/anthropic",
            )
            self.assertEqual(executor._extra_env["CLAUDE_CODE_API_KEY_HELPER_TTL_MS"], "900000")
            self.assertIn(
                'databricks auth token --host "https://example.cloud.databricks.com"',
                executor._extra_env["OMNIGENT_CLAUDE_API_KEY_HELPER"],
            )
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", executor._extra_env)

    def test_databricks_explicit_profile_selects_by_profile(self):
        """An explicit ``databricks_profile`` makes the token helper select
        the bearer by ``--profile`` (unambiguous), not ``--host``.

        Two ``~/.databrickscfg`` profiles can share one host, which makes
        ``databricks auth token --host`` fail ("Use --profile to specify
        which profile") → empty token → a silent ``status=401``. Selecting
        by ``--profile`` avoids that.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ),
        ):
            executor = ClaudeSDKExecutor(gateway=True, databricks_profile="oss")
        helper = executor._extra_env["OMNIGENT_CLAUDE_API_KEY_HELPER"]
        # Proves the selector is --profile, not --host. A regression to --host
        # makes a two-profiles-one-host workspace yield an empty token → 401.
        self.assertIn('databricks auth token --profile "oss"', helper)
        # Scope to the CLI mint: it selects by --profile. The sdk fallback
        # separately passes --host for its own workspace guard (identity is
        # still pinned by --profile), so assert on the mint, not the whole helper.
        self.assertNotIn("databricks auth token --host", helper)
        # `--force-refresh` only exists in Databricks CLI >= v0.296.0, so it
        # stays behind a `--help` capability probe — an older CLI rejects the
        # unknown flag and yields an empty token → silent 401.
        self.assertIn("databricks auth token --help", helper)
        # And even where it exists it is only ATTEMPTED: it fails outright on a
        # stale refresh token, so an empty result must fall back to the cached
        # token rather than turning a usable credential into an auth failure.
        self.assertIn("--force-refresh", helper)
        self.assertIn('if [ -z "$token" ]; then', helper)

    def test_databricks_flag_no_creds_raises(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("omnigent.inner.claude_sdk_executor._resolve_gateway_env", return_value={}),
        ):
            with self.assertRaises(EnvironmentError):
                ClaudeSDKExecutor(gateway=True)

    def test_databricks_flag_with_host_override(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("omnigent.inner.databricks_executor._read_databrickscfg") as read_cfg,
        ):
            executor = ClaudeSDKExecutor(
                gateway=True,
                databricks_profile="missing-profile",
                gateway_host="https://example.databricks.com/",
                base_url_override="https://example.databricks.com/ai-gateway/anthropic",
                gateway_auth_command="printf token",
            )

        read_cfg.assert_not_called()
        self.assertEqual(
            executor._extra_env["ANTHROPIC_BASE_URL"],
            "https://example.databricks.com/ai-gateway/anthropic",
        )
        self.assertEqual(
            executor._extra_env["OMNIGENT_CLAUDE_API_KEY_HELPER"],
            "printf token",
        )
        self.assertEqual(executor._extra_env["ENABLE_TOOL_SEARCH"], "true")

    def test_databricks_flag_with_host_override_requires_base_url(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(OSError, "GATEWAY_BASE_URL"),
        ):
            ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://example.databricks.com/",
                gateway_auth_command="printf token",
            )

    def test_databricks_flag_with_host_override_requires_auth_command(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with (
            patch.dict("os.environ", {}, clear=True),
            self.assertRaisesRegex(OSError, "GATEWAY_AUTH_COMMAND"),
        ):
            ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://example.databricks.com/",
                base_url_override="https://example.databricks.com/ai-gateway/anthropic",
            )

    def test_databricks_false_no_extra_env(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.spec.types import RetryPolicy

        with patch.dict("os.environ"):
            os.environ.pop("OMNIGENT_CLAUDE_CODE_ENTRYPOINT", None)
            executor = ClaudeSDKExecutor(gateway=False)
        # gateway=False → no Databricks env, but Tool Search and RetryPolicy
        # CLI env are always merged in.
        self.assertEqual(
            executor._extra_env,
            {
                "ENABLE_TOOL_SEARCH": "true",
                **RetryPolicy().claude_cli.env(),
            },
        )

    def test_databricks_profile_default_model_used_when_unset(self):
        """gateway=True (profile-derived) + no model → Databricks default.

        On the Databricks-profile gateway path (transport derived from
        ~/.databrickscfg, no gateway base URL supplied directly), a missing
        model falls back to the Databricks default. The neutral
        generic-provider gateway path never does this (see
        ``test_neutral_gateway_no_model_does_not_inject_databricks_default``).

        Live model discovery is stubbed unavailable here so the resolver drops
        to the bundled catalog — its documented last resort; the discovery-first
        path is covered by ``test_databricks_profile_uses_discovered_model``.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t():
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True)

            captured: dict[str, str | None] = {}
            event_loop_thread = threading.get_ident()

            def _resolve_model(provider_name: str, *, family: str) -> SimpleNamespace:
                self.assertNotEqual(threading.get_ident(), event_loop_thread)
                self.assertEqual((provider_name, family), ("databricks", "claude"))
                return SimpleNamespace(model_id="catalog-databricks-claude-default")

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["model"] = model
                raise RuntimeError("stop after model resolution")

            with (
                patch(
                    "omnigent.models.databricks_model_discovery.discover_databricks_claude_catalog",
                    side_effect=RuntimeError("live listing unavailable"),
                ),
                patch(
                    "omnigent.models.model_catalog.resolve_catalog_model",
                    side_effect=_resolve_model,
                ),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertEqual(captured["model"], "catalog-databricks-claude-default")

        _run(_t())

    def test_databricks_profile_uses_discovered_model(self):
        """gateway=True (profile-derived) + no model → the workspace's live model.

        The resolver prefers the live Unity Catalog listing over the bundled
        catalog, walking the ``opus > sonnet > haiku > fable`` precedence
        claude-native falls back to; the bundled ``databricks-*`` catalog is
        only the last resort (see ``..._default_model_used_when_unset``).
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t():
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True)

            captured: dict[str, str | None] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["model"] = model
                raise RuntimeError("stop after model resolution")

            with (
                patch(
                    "omnigent.runtime.credentials.databricks.resolve_databricks_workspace",
                    return_value=SimpleNamespace(
                        host="https://example.cloud.databricks.com", token="dapi_test_token"
                    ),
                ),
                patch(
                    "omnigent.models.databricks_model_discovery.discover_databricks_claude_catalog",
                    return_value=SimpleNamespace(
                        families={
                            "sonnet": "system.ai.claude-sonnet-5",
                            "opus": "system.ai.claude-opus-5",
                        }
                    ),
                ),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            # opus outranks sonnet in the family precedence.
            self.assertEqual(captured["model"], "system.ai.claude-opus-5")

        _run(_t())

    def test_databricks_profile_model_resolution_cached_across_turns(self):
        """The unpinned-session catalog resolution runs once per executor."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t():
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True)

            captured: list[str | None] = []
            resolve_calls: list[str | None] = []

            def fake_resolver(profile):
                resolve_calls.append(profile)
                return "system.ai.claude-opus-5"

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured.append(model)
                raise RuntimeError("stop after model resolution")

            with (
                patch(
                    "omnigent.inner.claude_sdk_executor._resolve_databricks_claude_model",
                    side_effect=fake_resolver,
                ),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                for _ in range(2):
                    with self.assertRaises(RuntimeError):
                        async for _ in executor.run_turn(
                            [{"role": "user", "content": "hi"}], [], ""
                        ):
                            pass

            self.assertEqual(captured, ["system.ai.claude-opus-5"] * 2)
            self.assertEqual(len(resolve_calls), 1)

        _run(_t())

    def test_databricks_profile_model_substitution_warns(self):
        """An unpinned session's silent model pick must emit a WARNING."""
        from omnigent.inner.claude_sdk_executor import _resolve_databricks_claude_model

        with (
            patch(
                "omnigent.runtime.credentials.databricks.resolve_databricks_workspace",
                return_value=SimpleNamespace(
                    host="https://example.cloud.databricks.com", token="dapi_test_token"
                ),
            ),
            patch(
                "omnigent.models.databricks_model_discovery.discover_databricks_claude_catalog",
                return_value=SimpleNamespace(
                    families={
                        "sonnet": "system.ai.claude-sonnet-5",
                        "opus": "system.ai.claude-opus-5",
                    }
                ),
            ),
            self.assertLogs("omnigent.inner.claude_sdk_executor", level="WARNING") as logs,
        ):
            resolved = _resolve_databricks_claude_model("repro")

        self.assertEqual(resolved, "system.ai.claude-opus-5")
        self.assertTrue(
            any("system.ai.claude-opus-5" in message for message in logs.output),
            f"no WARNING names the substituted model: {logs.output}",
        )

    def test_databricks_catalog_fallback_substitution_warns(self):
        """The bundled-catalog fallback is also a substitution; it must warn."""
        from omnigent.inner.claude_sdk_executor import _resolve_databricks_claude_model

        with (
            patch(
                "omnigent.models.databricks_model_discovery.discover_databricks_claude_catalog",
                side_effect=RuntimeError("live listing unavailable"),
            ),
            patch(
                "omnigent.models.model_catalog.resolve_catalog_model",
                return_value=SimpleNamespace(model_id="databricks-claude-default"),
            ),
            self.assertLogs("omnigent.inner.claude_sdk_executor", level="WARNING") as logs,
        ):
            resolved = _resolve_databricks_claude_model("repro")

        self.assertEqual(resolved, "databricks-claude-default")
        self.assertTrue(
            any(
                "databricks-claude-default" in message and "bundled catalog" in message
                for message in logs.output
            ),
            f"no WARNING names the catalog-fallback model: {logs.output}",
        )

    def test_neutral_gateway_no_model_does_not_inject_databricks_default(self):
        """Neutral gateway (base URL supplied directly) + no model → ``None``.

        The neutral generic-provider gateway transport never falls back to a
        ``databricks-*`` model: the Omnigent producer resolves a concrete model
        before spawning, so the executor passes ``None`` through to the SDK.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://gateway.example.com",
                base_url_override="https://gateway.example.com/v1",
                gateway_auth_command="printf token",
            )

            captured: dict[str, str | None] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["model"] = model
                raise RuntimeError("stop after model resolution")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertIsNone(captured["model"])

        _run(_t())

    def test_gateway_pins_family_aliases_to_served_ids(self):
        """A gateway turn pins every family alias to an id the gateway serves.

        Claude Code's refusal-fallback resolves the ``opus`` alias through
        ``ANTHROPIC_DEFAULT_OPUS_MODEL``; unpinned it lands on a canonical
        vendor id a gateway serving its own ids rejects (``model_not_found``).
        The executor lists the gateway's models and pins each alias to a
        served id. See ``_apply_gateway_model_vocabulary``.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.models.model_catalog import ModelEntry, ModelListing

        async def _t():
            executor = ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://gateway.example.com",
                base_url_override="https://gateway.example.com/anthropic",
                gateway_auth_command="printf token",
                model="gw-claude-fable-5",
            )

            captured: dict[str, dict[str, str]] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["env"] = dict(options.env or {})
                captured["settings"] = json.loads(options.settings or "{}")
                raise RuntimeError("stop after env assembly")

            listing = ModelListing(
                source="openai-compatible",
                verified=True,
                models=(
                    ModelEntry(id="gw-claude-fable-5", family="claude"),
                    ModelEntry(id="gw-claude-opus-4-7", family="claude"),
                    ModelEntry(id="gw-claude-opus-4-8", family="claude"),
                    # A newer Opus alongside 4.8 — the shape that broke the
                    # refusal-fallback: the alias must track the newest while
                    # the rewrites still cover the older generation the CLI's
                    # own route table can name.
                    ModelEntry(id="gw-claude-opus-5", family="claude"),
                    ModelEntry(id="gw-claude-sonnet-5", family="claude"),
                    ModelEntry(id="gw-claude-haiku-4-5", family="claude"),
                    ModelEntry(id="gw-gpt-5-6", family="openai"),
                ),
                note="",
            )
            with (
                patch("omnigent.models.model_catalog.listing_for_provider", return_value=listing),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            env = captured["env"]
            self.assertEqual(env["CLAUDE_AGENT_SDK_CLIENT_APP"], "omnigent")
            # Newest served generation per family; the non-Claude id is ignored.
            self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "gw-claude-opus-5")
            self.assertEqual(env["ANTHROPIC_DEFAULT_FABLE_MODEL"], "gw-claude-fable-5")
            self.assertEqual(env["ANTHROPIC_DEFAULT_SONNET_MODEL"], "gw-claude-sonnet-5")
            self.assertEqual(env["ANTHROPIC_DEFAULT_HAIKU_MODEL"], "gw-claude-haiku-4-5")
            # Every served Claude generation is reachable by its canonical
            # spelling, so whichever id the CLI's route table names resolves —
            # including the 4.8 the newest-Opus alias no longer points at.
            self.assertEqual(
                captured["settings"]["modelOverrides"],
                {
                    "claude-fable-5": "gw-claude-fable-5",
                    "claude-opus-4-7": "gw-claude-opus-4-7",
                    "claude-opus-4-8": "gw-claude-opus-4-8",
                    "claude-opus-5": "gw-claude-opus-5",
                    "claude-sonnet-5": "gw-claude-sonnet-5",
                    "claude-haiku-4-5": "gw-claude-haiku-4-5",
                },
            )

        _run(_t())

    def test_gateway_listing_without_claude_models_pins_nothing(self):
        """A gateway that lists no Claude models leaves the aliases unpinned.

        The served ids are unknown, so the executor must not invent pins;
        an unpinned alias is today's behavior, not a regression.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.models.model_catalog import ModelEntry, ModelListing

        async def _t():
            executor = ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://gateway.example.com",
                base_url_override="https://gateway.example.com/v1",
                gateway_auth_command="printf token",
                model="gpt-5",
            )

            captured: dict[str, dict[str, str]] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["env"] = dict(options.env or {})
                raise RuntimeError("stop after env assembly")

            listing = ModelListing(
                source="openai-compatible",
                verified=True,
                models=(ModelEntry(id="gpt-5", family="openai"),),
                note="",
            )
            with (
                patch("omnigent.models.model_catalog.listing_for_provider", return_value=listing),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertFalse({k for k in captured["env"] if k.startswith("ANTHROPIC_DEFAULT_")})

        _run(_t())

    def test_claude_code_entrypoint_is_forwarded_when_set(self):
        """``OMNIGENT_CLAUDE_CODE_ENTRYPOINT`` is sent to the CLI as ``CLAUDE_CODE_ENTRYPOINT``."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        with patch.dict("os.environ", {"OMNIGENT_CLAUDE_CODE_ENTRYPOINT": "cli"}):
            executor = ClaudeSDKExecutor(model="claude-sonnet-4-5")
        self.assertEqual(executor._extra_env["CLAUDE_CODE_ENTRYPOINT"], "cli")

        with patch.dict("os.environ"):
            os.environ.pop("OMNIGENT_CLAUDE_CODE_ENTRYPOINT", None)
            executor = ClaudeSDKExecutor(model="claude-sonnet-4-5")
        self.assertNotIn("CLAUDE_CODE_ENTRYPOINT", executor._extra_env)

    def test_explicit_family_pins_are_not_overwritten(self):
        """Pre-set ``ANTHROPIC_DEFAULT_*_MODEL`` pins win over the listing.

        A launch config that already pins every alias must be respected
        verbatim. The gateway is still listed, because pinning an alias says
        nothing about how this gateway spells the canonical ids Claude Code
        names on its own — those rewrites are needed either way.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.models.model_catalog import ModelEntry, ModelListing

        async def _t():
            executor = ClaudeSDKExecutor(
                gateway=True,
                gateway_host="https://gateway.example.com",
                base_url_override="https://gateway.example.com/anthropic",
                gateway_auth_command="printf token",
                model="gw-claude-fable-5",
            )
            executor._extra_env["ANTHROPIC_DEFAULT_FABLE_MODEL"] = "pinned-fable"
            executor._extra_env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "pinned-opus"
            executor._extra_env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "pinned-sonnet"
            executor._extra_env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "pinned-haiku"

            captured: dict[str, dict[str, str]] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["env"] = dict(options.env or {})
                captured["settings"] = json.loads(options.settings or "{}")
                raise RuntimeError("stop after env assembly")

            listing = ModelListing(
                source="openai-compatible",
                verified=True,
                models=(ModelEntry(id="gw-claude-opus-4-8", family="claude"),),
                note="",
            )
            with (
                patch("omnigent.models.model_catalog.listing_for_provider", return_value=listing),
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            for alias in ("FABLE", "OPUS", "SONNET", "HAIKU"):
                self.assertEqual(
                    captured["env"][f"ANTHROPIC_DEFAULT_{alias}_MODEL"],
                    f"pinned-{alias.lower()}",
                )
            self.assertEqual(
                captured["settings"]["modelOverrides"],
                {"claude-opus-4-8": "gw-claude-opus-4-8"},
            )

        _run(_t())

    def test_gateway_model_passes_through(self):
        """Explicit model on the gateway path passes through unchanged."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t():
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True, model="databricks-claude-sonnet-4-6")

            captured: dict[str, str | None] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["model"] = model
                raise RuntimeError("stop after model resolution")

            with (
                patch(
                    "omnigent.models.model_catalog.subprocess.run",
                    side_effect=AssertionError("unexpected authentication subprocess"),
                ) as auth_subprocess,
                patch(
                    "omnigent.models.model_catalog.httpx.Client",
                    side_effect=AssertionError("unexpected model-listing HTTP client"),
                ) as http_client,
                patch.object(
                    executor,
                    "_get_or_create_client",
                    side_effect=fake_get_or_create_client,
                ),
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertEqual(captured["model"], "databricks-claude-sonnet-4-6")
            auth_subprocess.assert_not_called()
            http_client.assert_not_called()

        _run(_t())

    def test_no_databricks_default_when_databricks_off(self):
        """gateway=False keeps prior behavior: None falls through to the SDK."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor(gateway=False)
            captured: dict[str, str | None] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["model"] = model
                raise RuntimeError("stop after model resolution")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertIsNone(captured["model"])

        _run(_t())

    def test_databricks_opus_pins_thinking_to_adaptive(self):
        """gateway=True + opus sets ``thinking={"type": "adaptive", "display": "summarized"}``."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t(model):
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True, model=model)

            captured: dict[str, object] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["thinking"] = getattr(options, "thinking", None)
                raise RuntimeError("stop after options built")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertEqual(captured["thinking"], {"type": "adaptive", "display": "summarized"})

        # Legacy serving-endpoint and Unity Catalog spellings of the same tier.
        for model in ("databricks-claude-opus-4-7", "system.ai.claude-opus-4-7"):
            with self.subTest(model=model):
                _run(_t(model))

    def test_databricks_fable_pins_thinking_to_adaptive(self):
        """gateway=True + fable sets ``thinking={"type": "adaptive", "display": "summarized"}``.

        Fable (claude-fable-5) shares Opus 4.7/4.8's adaptive-only thinking
        surface, so the Databricks gateway rejects the CLI's default
        thinking=enabled for it too. If this stays unset, a fable session
        through the gateway 400s on the first request.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t(model):
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True, model=model)

            captured: dict[str, object] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["thinking"] = getattr(options, "thinking", None)
                raise RuntimeError("stop after options built")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertEqual(captured["thinking"], {"type": "adaptive", "display": "summarized"})

        # Legacy serving-endpoint and Unity Catalog spellings of the same tier.
        for model in ("databricks-claude-fable-5", "system.ai.claude-fable-5"):
            with self.subTest(model=model):
                _run(_t(model))

    def test_databricks_sonnet_leaves_thinking_unset(self):
        """gateway=True + non-adaptive-tier model preserves CLI default thinking."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.databricks_executor import DatabricksCredentials

        async def _t():
            with patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.cloud.databricks.com",
                    token="dapi_test_token",
                ),
            ):
                executor = ClaudeSDKExecutor(gateway=True, model="databricks-claude-sonnet-4-6")

            captured: dict[str, object] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["thinking"] = getattr(options, "thinking", None)
                raise RuntimeError("stop after options built")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertIsNone(captured["thinking"])

        _run(_t())

    def test_no_databricks_leaves_thinking_unset(self):
        """gateway=False does not touch ``thinking``; preserves CLI default."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor(gateway=False, model="claude-opus-4-7")
            captured: dict[str, object] = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["thinking"] = getattr(options, "thinking", None)
                raise RuntimeError("stop after options built")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertIsNone(captured["thinking"])

        _run(_t())

    def test_force_close_client_uses_process_tree_termination(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _Transport:
            def __init__(self):
                self._process = SimpleNamespace(returncode=None, pid=12345, wait=AsyncMock())
                self._stdout_stream = object()
                self._stdin_stream = object()
                self._stderr_stream = object()
                self._stderr_task_group = None
                self._ready = True

        client = SimpleNamespace(_query=None, _transport=_Transport())

        async def _t():
            with patch(
                "omnigent.inner.claude_sdk_executor._terminate_process_tree"
            ) as terminate_tree:
                await ClaudeSDKExecutor._force_close_client(client)
            terminate_tree.assert_called_once()

        _run(_t())

    def test_force_close_client_handles_sdk_without_stderr_task_group(self):
        # Regression: claude-agent-sdk >=0.2.x renamed the stderr reader from an
        # anyio task group (`_stderr_task_group`) to a single `_stderr_task`
        # TaskHandle. A transport shaped like the current SDK (no
        # `_stderr_task_group` attribute at all) must not raise AttributeError
        # out of `_force_close_client` — that exception escaped the runner's
        # lifespan shutdown and crashed it on every session stop.
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        stderr_task = SimpleNamespace(cancel=Mock())

        class _Transport:
            def __init__(self):
                self._process = SimpleNamespace(returncode=None, pid=12345, wait=AsyncMock())
                self._stdout_stream = object()
                self._stdin_stream = object()
                self._stderr_stream = object()
                self._stderr_task = stderr_task  # current SDK shape
                self._ready = True

        transport = _Transport()
        client = SimpleNamespace(_query=None, _transport=transport)

        async def _t():
            with patch(
                "omnigent.inner.claude_sdk_executor._terminate_process_tree"
            ) as terminate_tree:
                await ClaudeSDKExecutor._force_close_client(client)
            terminate_tree.assert_called_once()

        _run(_t())

        # New-shape stderr task was cancelled, the missing legacy attribute was
        # never created, and the handle was cleared.
        stderr_task.cancel.assert_called_once()
        self.assertFalse(hasattr(transport, "_stderr_task_group"))
        self.assertIsNone(transport._stderr_task)

    def test_claude_internal_write_files_omits_missing_config(self):
        from omnigent.inner.claude_sdk_executor import _claude_internal_write_files

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            config_path = home / ".claude.json"
            self.assertFalse(config_path.exists())
            with patch("omnigent.inner.claude_sdk_executor.pathlib.Path.home", return_value=home):
                paths = _claude_internal_write_files()

            self.assertEqual(paths, [])
            self.assertFalse(config_path.exists())

    def test_claude_internal_write_files_includes_existing_config(self):
        from omnigent.inner.claude_sdk_executor import _claude_internal_write_files

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            config_path = home / ".claude.json"
            config_path.write_text("{}\n", encoding="utf-8")
            with patch("omnigent.inner.claude_sdk_executor.pathlib.Path.home", return_value=home):
                paths = _claude_internal_write_files()

            self.assertEqual(paths, [config_path])

    def test_claude_internal_write_files_includes_credentials_when_present(self):
        from omnigent.inner.claude_sdk_executor import _claude_internal_write_files

        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            config_path = home / ".claude.json"
            config_path.write_text("{}\n", encoding="utf-8")
            credentials_path = home / ".claude" / ".credentials.json"
            credentials_path.parent.mkdir(parents=True, exist_ok=True)
            credentials_path.write_text("{}\n", encoding="utf-8")
            with patch("omnigent.inner.claude_sdk_executor.pathlib.Path.home", return_value=home):
                paths = _claude_internal_write_files()

            self.assertEqual(paths, [config_path, credentials_path])


# ---------------------------------------------------------------------------
# Tests: MCP tool building
# ---------------------------------------------------------------------------


class TestBuildMcpTools(unittest.TestCase):
    def test_builds_tools_from_schemas(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        async def mock_executor(name, args):
            return {"result": "ok"}

        schemas = [
            {
                "name": "calc",
                "description": "Calculate",
                "parameters": {
                    "type": "object",
                    "properties": {"expr": {"type": "string"}},
                },
            },
        ]
        tools = _build_mcp_tools(schemas, mock_executor)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].name, "calc")

    def test_empty_schemas(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        self.assertEqual(_build_mcp_tools([], None), [])

    def test_handler_calls_executor(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        calls = []

        async def mock_executor(name, args):
            calls.append((name, args))
            return {"result": 42}

        schemas = [
            {
                "name": "add",
                "description": "Add",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            }
        ]
        tools = _build_mcp_tools(schemas, mock_executor)
        result = _run(tools[0].handler({"a": 1}))
        self.assertEqual(calls, [("add", {"a": 1})])
        self.assertIn("content", result)
        parsed = json.loads(result["content"][0]["text"])
        self.assertEqual(parsed["result"], 42)
        self.assertNotIn("isError", result)

    def test_handler_keeps_unicode_readable_and_surrogates_transport_safe(self):
        # The handler's text is what the model reads. \uXXXX escapes make every
        # non-ASCII character six characters long and several times the tokens,
        # which pushes ordinary non-English tool output past the harness's size
        # limit for tool results.
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        async def mock_executor(name, args):
            return {"stdout": "Спикер 1: привет", "path": "recording-\udcff.txt"}

        schemas = [
            {
                "name": "sh",
                "description": "Shell",
                "parameters": {"type": "object", "properties": {}},
            }
        ]
        tools = _build_mcp_tools(schemas, mock_executor)
        result = _run(tools[0].handler({}))
        text = result["content"][0]["text"]
        self.assertIn("Спикер 1: привет", text)
        self.assertNotIn("\\u0421", text)
        self.assertIn("\\udcff", text)
        text.encode("utf-8")
        self.assertEqual(
            json.loads(text),
            {"stdout": "Спикер 1: привет", "path": "recording-\udcff.txt"},
        )

    def test_handler_error_keeps_unicode_readable_and_surrogates_transport_safe(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        async def mock_executor(name, args):
            raise RuntimeError("ошибка для recording-\udcff.txt")

        schemas = [
            {
                "name": "sh",
                "description": "Shell",
                "parameters": {"type": "object", "properties": {}},
            }
        ]

        result = _run(_build_mcp_tools(schemas, mock_executor)[0].handler({}))

        self.assertTrue(result["isError"])
        text = result["content"][0]["text"]
        self.assertIn("ошибка", text)
        self.assertIn("\\udcff", text)
        text.encode("utf-8")
        self.assertEqual(json.loads(text), {"error": "ошибка для recording-\udcff.txt"})

    def test_handler_marks_blocked_result_as_error(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        async def mock_executor(name, args):
            return {"blocked": True, "reason": "Exceeded max tool calls"}

        schemas = [
            {
                "name": "add",
                "description": "Add",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            }
        ]
        tools = _build_mcp_tools(schemas, mock_executor)
        result = _run(tools[0].handler({"a": 1}))
        self.assertTrue(result["isError"])
        parsed = json.loads(result["content"][0]["text"])
        self.assertTrue(parsed["blocked"])

    def test_handler_marks_error_result_as_error(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        async def mock_executor(name, args):
            return {"error": "boom"}

        schemas = [
            {
                "name": "add",
                "description": "Add",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            }
        ]
        tools = _build_mcp_tools(schemas, mock_executor)
        result = _run(tools[0].handler({"a": 1}))
        self.assertTrue(result["isError"])
        parsed = json.loads(result["content"][0]["text"])
        self.assertEqual(parsed["error"], "boom")

    def test_handler_no_executor(self):
        from omnigent.inner.claude_sdk_executor import _build_mcp_tools

        schemas = [
            {
                "name": "x",
                "description": "x",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            }
        ]
        tools = _build_mcp_tools(schemas, None)
        result = _run(tools[0].handler({}))
        parsed = json.loads(result["content"][0]["text"])
        self.assertIn("error", parsed)


# ---------------------------------------------------------------------------
# Tests: Databricks env resolution
# ---------------------------------------------------------------------------


class TestResolveGatewayEnv(unittest.TestCase):
    def test_from_profile(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://example.databricks.com",
                    token="dapi_abc123",
                ),
            ),
        ):
            env = _resolve_gateway_env()
            self.assertEqual(
                env["ANTHROPIC_BASE_URL"],
                "https://example.databricks.com/ai-gateway/anthropic",
            )
            self.assertEqual(env["CLAUDE_CODE_API_KEY_HELPER_TTL_MS"], "900000")
            self.assertIn(
                'databricks auth token --host "https://example.databricks.com"',
                env["OMNIGENT_CLAUDE_API_KEY_HELPER"],
            )
            self.assertEqual(
                env["ANTHROPIC_CUSTOM_HEADERS"],
                "x-databricks-use-coding-agent-mode: true",
            )
            self.assertNotIn("ANTHROPIC_AUTH_TOKEN", env)

    def test_databricks_gateway_negotiates_betas(self):
        """A real Databricks Unity Gateway base URL negotiates betas, not disables them.

        Blanket-disabling betas makes Claude Code strip ``interleaved-thinking``,
        which the Databricks gateway then rejects with a thinking-block 400. On a
        genuine gateway we set ``CLAUDE_CODE_USE_GATEWAY`` and leave the disable
        flag off (matching claude-native).
        """
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(
                    host="https://wkspc.cloud.databricks.com",
                    token="dapi_abc123",
                ),
            ),
        ):
            env = _resolve_gateway_env()
        self.assertEqual(env["CLAUDE_CODE_USE_GATEWAY"], "1")
        self.assertNotIn("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", env)
        self.assertEqual(
            env["ANTHROPIC_CUSTOM_HEADERS"].splitlines(),
            [
                "x-databricks-use-coding-agent-mode: true",
                "Databricks-Custom-Coding-Agent: claude-code",
                "Databricks-Custom-Client-Surfaces: omnigent",
            ],
        )

    def test_non_databricks_gateway_keeps_beta_disable(self):
        """A gateway host outside the trusted Databricks domains keeps the workaround.

        A generic gateway (or a mock server) can't negotiate betas, so the
        original ``CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS`` behavior is preserved.
        """
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                # Not under a trusted Databricks parent domain.
                return_value=DatabricksCredentials(
                    host="https://example.databricks.com", token="t"
                ),
            ),
        ):
            env = _resolve_gateway_env()
        self.assertEqual(env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"], "1")
        self.assertNotIn("CLAUDE_CODE_USE_GATEWAY", env)

    def test_strips_trailing_slash(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env
        from omnigent.inner.databricks_executor import DatabricksCredentials

        with (
            patch.dict("os.environ", {}, clear=True),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg",
                return_value=DatabricksCredentials(host="https://my-workspace.com/", token="tok"),
            ),
        ):
            env = _resolve_gateway_env()
            self.assertFalse(env["ANTHROPIC_BASE_URL"].endswith("//"))
            self.assertTrue(env["ANTHROPIC_BASE_URL"].endswith("/ai-gateway/anthropic"))

    def test_no_creds_returns_empty(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("omnigent.inner.databricks_executor._read_databrickscfg", return_value=None),
            # Host derivation no longer needs a static token, so "no creds"
            # must also mean no host is resolvable from ~/.databrickscfg.
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg_host",
                return_value=None,
            ),
        ):
            env = _resolve_gateway_env()
            self.assertEqual(env, {})

    def test_oauth_profile_without_token_resolves_from_host(self):
        """An OAuth U2M profile (host, no static token) must resolve.

        The SDK resolver returns ``None`` when it cannot mint a bearer
        (e.g. no Databricks CLI OAuth state on this machine), but the
        profile's ``host`` is always present — and the generated auth
        command mints the bearer at request time — so the gateway env
        must still resolve instead of failing with "requires gateway
        credentials".
        """
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        with (
            patch.dict("os.environ", {}, clear=True),
            patch("omnigent.inner.databricks_executor._read_databrickscfg", return_value=None),
            patch(
                "omnigent.inner.databricks_executor._read_databrickscfg_host",
                return_value="https://adb-12345.azuredatabricks.net",
            ),
        ):
            env = _resolve_gateway_env("my-oauth-profile")
        self.assertEqual(
            env["ANTHROPIC_BASE_URL"],
            "https://adb-12345.azuredatabricks.net/ai-gateway/anthropic",
        )
        self.assertIn(
            'databricks auth token --profile "my-oauth-profile"',
            env["OMNIGENT_CLAUDE_API_KEY_HELPER"],
        )

    def test_host_override_skips_profile_lookup(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        with patch("omnigent.inner.databricks_executor._read_databrickscfg") as read_cfg:
            env = _resolve_gateway_env(
                profile="missing-profile",
                host_override="https://example.databricks.com/",
                base_url_override="https://example.databricks.com/ai-gateway/anthropic",
                auth_command_override="printf token",
            )

        read_cfg.assert_not_called()
        self.assertEqual(
            env["ANTHROPIC_BASE_URL"],
            "https://example.databricks.com/ai-gateway/anthropic",
        )
        self.assertEqual(env["OMNIGENT_CLAUDE_API_KEY_HELPER"], "printf token")
        self.assertEqual(
            env["ANTHROPIC_CUSTOM_HEADERS"],
            "x-databricks-use-coding-agent-mode: true",
        )

    def test_generic_provider_gateway_omits_databricks_header(self):
        """Non-Databricks gateways must not receive the Databricks mode header."""
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        env = _resolve_gateway_env(
            base_url_override="https://mock-llm.example/v1",
            auth_command_override="printf sk-test",
        )
        self.assertNotIn("ANTHROPIC_CUSTOM_HEADERS", env)

    def test_generic_provider_on_unity_gateway_gets_attribution(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        # The worker's own custom headers belong to whatever launched it, not the gateway.
        ambient = {"ANTHROPIC_CUSTOM_HEADERS": "X-Trace: drop", "OMNIGENT_CLIENT_SURFACE": "web"}
        with patch.dict("os.environ", ambient, clear=True):
            env = _resolve_gateway_env(
                base_url_override="https://wkspc.cloud.databricks.com/ai-gateway/anthropic",
                auth_command_override="printf sk-test",
            )
        self.assertEqual(env["CLAUDE_CODE_USE_GATEWAY"], "1")
        self.assertNotIn("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", env)
        self.assertEqual(
            env["ANTHROPIC_CUSTOM_HEADERS"].splitlines(),
            [
                "Databricks-Custom-Coding-Agent: claude-code",
                "Databricks-Custom-Client-Surfaces: omnigent-web",
            ],
        )

    def test_host_override_requires_base_url(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        with self.assertRaisesRegex(OSError, "GATEWAY_BASE_URL"):
            _resolve_gateway_env(
                host_override="https://example.databricks.com/",
                auth_command_override="printf token",
            )

    def test_host_override_requires_auth_command(self):
        from omnigent.inner.claude_sdk_executor import _resolve_gateway_env

        with self.assertRaisesRegex(OSError, "GATEWAY_AUTH_COMMAND"):
            _resolve_gateway_env(
                host_override="https://example.databricks.com/",
                base_url_override="https://example.databricks.com/ai-gateway/anthropic",
            )


# ---------------------------------------------------------------------------
# Tests: Gateway model vocabulary (alias pins + canonical rewrites)
# ---------------------------------------------------------------------------


class TestGatewayModelVocabulary(unittest.TestCase):
    def test_pins_map_served_families_to_env_vars(self):
        from omnigent.inner.claude_sdk_executor import _gateway_model_vocabulary
        from omnigent.models.model_catalog import ModelEntry, ModelListing

        listing = ModelListing(
            source="openai-compatible",
            verified=True,
            models=(
                ModelEntry(id="databricks-claude-opus-4-8", family="claude"),
                ModelEntry(id="databricks-claude-fable-5", family="claude"),
                ModelEntry(id="databricks-gpt-5-6", family="openai"),
            ),
            note="",
        )
        with patch(
            "omnigent.models.model_catalog.listing_for_provider", return_value=listing
        ) as lister:
            vocabulary = _gateway_model_vocabulary(
                "https://gw.example.com/anthropic", "printf tok"
            )
        self.assertEqual(
            vocabulary.alias_pins,
            {
                "ANTHROPIC_DEFAULT_OPUS_MODEL": "databricks-claude-opus-4-8",
                "ANTHROPIC_DEFAULT_FABLE_MODEL": "databricks-claude-fable-5",
            },
        )
        # Same listing, second half of the vocabulary: the canonical spelling
        # Claude Code names itself, rewritten to what this gateway serves. The
        # non-Claude id contributes to neither half.
        self.assertEqual(
            vocabulary.model_overrides,
            {
                "claude-opus-4-8": "databricks-claude-opus-4-8",
                "claude-fable-5": "databricks-claude-fable-5",
            },
        )
        # The listing is fetched as a gateway transport: the base URL and the
        # auth command the CLI itself uses, not a Databricks profile.
        provider = lister.call_args.args[0]
        self.assertEqual(provider.base_url, "https://gw.example.com/anthropic")
        self.assertEqual(provider.auth_command, "printf tok")
        self.assertIsNone(provider.profile)

    def test_nothing_when_the_listing_has_no_claude_models(self):
        from omnigent.inner.claude_sdk_executor import (
            _EMPTY_GATEWAY_VOCABULARY,
            _gateway_model_vocabulary,
        )
        from omnigent.models.model_catalog import ModelListing

        listing = ModelListing(source="openai-compatible", verified=True, models=(), note="")
        with patch("omnigent.models.model_catalog.listing_for_provider", return_value=listing):
            self.assertEqual(
                _gateway_model_vocabulary("https://gw.example.com/anthropic", "printf tok"),
                _EMPTY_GATEWAY_VOCABULARY,
            )

    def test_nothing_when_the_listing_fails(self):
        """A failed listing is swallowed — today's behavior is the safe default."""
        from omnigent.inner.claude_sdk_executor import (
            _EMPTY_GATEWAY_VOCABULARY,
            _gateway_model_vocabulary,
        )

        with patch(
            "omnigent.models.model_catalog.listing_for_provider",
            side_effect=RuntimeError("listing unavailable"),
        ):
            self.assertEqual(
                _gateway_model_vocabulary("https://gw.example.com/anthropic", "printf tok"),
                _EMPTY_GATEWAY_VOCABULARY,
            )

    def test_direct_endpoint_never_lists_or_pins(self):
        """Off the gateway transport the CLI resolves canonical ids itself."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        executor = ClaudeSDKExecutor()
        env = {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"}
        listing = Mock()
        with patch("omnigent.models.model_catalog.listing_for_provider", listing):
            overrides = _run(executor._apply_gateway_model_vocabulary(env, None))
        self.assertEqual(env, {"ANTHROPIC_BASE_URL": "https://api.anthropic.com"})
        self.assertEqual(overrides, {})
        listing.assert_not_called()

    def test_preset_pins_are_respected_but_rewrites_still_apply(self):
        """A launch config that pins aliases still needs the id rewrites.

        Pinning ``opus`` tells Claude Code which model the *alias* means. It
        says nothing about how this gateway spells the canonical ids the CLI
        names on its own, so the rewrites must be derived either way.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.models.model_catalog import ModelEntry, ModelListing

        listing = ModelListing(
            source="openai-compatible",
            verified=True,
            models=(ModelEntry(id="gw-claude-opus-4-8", family="claude"),),
            note="",
        )
        executor = ClaudeSDKExecutor.__new__(ClaudeSDKExecutor)
        executor._gateway = True
        executor._gateway_vocabulary = None
        env = {
            "ANTHROPIC_BASE_URL": "https://gw.example.com/anthropic",
            "ANTHROPIC_DEFAULT_OPUS_MODEL": "gw-claude-opus-5",
        }
        with patch("omnigent.models.model_catalog.listing_for_provider", return_value=listing):
            overrides = _run(executor._apply_gateway_model_vocabulary(env, "printf tok"))
        self.assertEqual(env["ANTHROPIC_DEFAULT_OPUS_MODEL"], "gw-claude-opus-5")
        self.assertEqual(overrides, {"claude-opus-4-8": "gw-claude-opus-4-8"})

    def test_settings_payload_carries_helper_and_rewrites(self):
        from omnigent.inner.claude_sdk_executor import _claude_settings_payload

        self.assertIsNone(_claude_settings_payload(None, {}))
        self.assertEqual(
            json.loads(_claude_settings_payload("printf tok", {"claude-opus-4-8": "gw-opus"})),
            {"apiKeyHelper": "printf tok", "modelOverrides": {"claude-opus-4-8": "gw-opus"}},
        )
        # No credential helper, but a gateway that still needs the rewrites.
        self.assertEqual(
            json.loads(_claude_settings_payload(None, {"claude-opus-4-8": "gw-opus"})),
            {"modelOverrides": {"claude-opus-4-8": "gw-opus"}},
        )


# ---------------------------------------------------------------------------
# Tests: Empty prompt handling
# ---------------------------------------------------------------------------


class TestEmptyPrompt(unittest.TestCase):
    def test_empty_prompt_yields_turn_complete(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor()
            events = [e async for e in executor.run_turn([], [], "")]
            self.assertEqual(len(events), 1)
            self.assertIsInstance(events[0], TurnComplete)
            # Empty-prompt short-circuit signals "no assistant text this
            # turn" via ``response=None`` rather than an empty string.
            self.assertIsNone(events[0].response)

        _run(_t())


class TestSystemMessages(unittest.TestCase):
    def test_databricks_auth_uses_api_key_helper_settings(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        captured_options = []

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types()):
            ResultMessage = _ResultMessage

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    captured_options.append(options)

                async def receive_response(self):
                    yield _ResultMessage("default", "ok")

        def _resolve_gateway_env(
            profile=None,
            *,
            host_override=None,
            base_url_override=None,
            auth_command_override=None,
            auth_refresh_interval_ms=None,
        ):
            return {
                "ANTHROPIC_BASE_URL": base_url_override or "https://host/ai-gateway/anthropic",
                "OMNIGENT_CLAUDE_API_KEY_HELPER": "databricks auth token --host https://host",
                "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "900000",
                "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
            }

        shim_upstream: dict[str, str] = {}

        async def _t():
            with (
                patch(
                    "omnigent.inner.claude_sdk_executor._resolve_gateway_env",
                    _resolve_gateway_env,
                ),
                patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK),
            ):
                executor = ClaudeSDKExecutor(
                    gateway=True,
                    gateway_host="https://host",
                    base_url_override="https://host/ai-gateway/anthropic",
                    gateway_auth_command="printf token",
                )
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hello"}],
                        [],
                        "",
                    )
                ]
            self.assertEqual(len(events), 1)
            # The gateway path routes the CLI through the local shim
            # (which restores thinking.display); record its target and
            # shut it down inside the loop that started it.
            self.assertIsNotNone(executor._gateway_shim)
            shim_upstream["base_url"] = executor._gateway_shim.base_url
            shim_upstream["upstream"] = executor._gateway_shim._upstream_base_url
            await executor._gateway_shim.aclose()

        _run(_t())

        self.assertEqual(len(captured_options), 1)
        settings = json.loads(captured_options[0].settings)
        self.assertEqual(
            settings["apiKeyHelper"],
            "databricks auth token --host https://host",
        )
        # The CLI talks to the loopback shim; the shim forwards to the
        # real gateway. A direct gateway URL here would mean the shim was
        # bypassed and opus thinking.display stays stripped.
        self.assertEqual(
            captured_options[0].env["ANTHROPIC_BASE_URL"],
            shim_upstream["base_url"],
        )
        self.assertTrue(shim_upstream["base_url"].startswith("http://127.0.0.1:"))
        self.assertEqual(shim_upstream["upstream"], "https://host/ai-gateway/anthropic")
        self.assertEqual(captured_options[0].env["CLAUDE_CODE_API_KEY_HELPER_TTL_MS"], "900000")
        self.assertEqual(captured_options[0].env["ENABLE_TOOL_SEARCH"], "true")
        self.assertNotIn("OMNIGENT_CLAUDE_API_KEY_HELPER", captured_options[0].env)
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", captured_options[0].env)

    def test_auth_retry_surfaces_executor_error(self):
        from claude_agent_sdk.types import (
            ClaudeAgentOptions as SDKClaudeAgentOptions,
        )
        from claude_agent_sdk.types import (
            StreamEvent as SDKStreamEvent,
        )
        from claude_agent_sdk.types import (
            SystemMessage as SDKSystemMessage,
        )

        from omnigent.inner.claude_sdk_executor import CLAUDE_AUTH_FAILED_CODE, ClaudeSDKExecutor

        class _Sentinel:
            pass

        class _FakeSDK(_sdk_types()):
            AssistantMessage = _Sentinel
            ResultMessage = _Sentinel
            UserMessage = _Sentinel
            SystemMessage = SDKSystemMessage
            StreamEvent = SDKStreamEvent
            ClaudeAgentOptions = SDKClaudeAgentOptions
            messages: list[object] = []

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t(error_status: int | None, retry_error: str):
            _FakeSDK.messages = [
                SDKSystemMessage(
                    subtype="api_retry",
                    data={
                        "type": "system",
                        "subtype": "api_retry",
                        "attempt": 1,
                        "max_retries": 10,
                        "retry_delay_ms": 500,
                        "error_status": error_status,
                        "error": retry_error,
                    },
                )
            ]
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hello"}],
                        [],
                        "",
                    )
                ]
            self.assertEqual(len(events), 1)
            self.assertIsInstance(events[0], ExecutorError)
            self.assertIn("authentication failed", events[0].message)
            self.assertIn(f"{retry_error}, status={error_status}", events[0].message)
            self.assertEqual(events[0].code, CLAUDE_AUTH_FAILED_CODE)
            # Non-gateway executor should point at the Claude Code login, not databrickscfg
            remediation = events[0].remediation or ""
            self.assertIn("claude auth login", remediation)
            self.assertNotIn("databrickscfg", remediation)
            self.assertIn(remediation, events[0].message)

        # Status alone (neutral error name) and error name alone each classify.
        for error_status, retry_error in (
            (401, "api_error"),
            (403, "api_error"),
            (None, "authentication_failed"),
        ):
            with self.subTest(error_status=error_status, retry_error=retry_error):
                _run(_t(error_status, retry_error))

    def test_auth_retry_databricks_gateway_mentions_databrickscfg(self):
        """Databricks-profile gateway auth errors should mention ~/.databrickscfg."""
        from claude_agent_sdk.types import (
            ClaudeAgentOptions as SDKClaudeAgentOptions,
        )
        from claude_agent_sdk.types import (
            StreamEvent as SDKStreamEvent,
        )
        from claude_agent_sdk.types import (
            SystemMessage as SDKSystemMessage,
        )

        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _Sentinel:
            pass

        class _FakeSDK(_sdk_types()):
            AssistantMessage = _Sentinel
            ResultMessage = _Sentinel
            UserMessage = _Sentinel
            SystemMessage = SDKSystemMessage
            StreamEvent = SDKStreamEvent
            ClaudeAgentOptions = SDKClaudeAgentOptions
            messages = [
                SDKSystemMessage(
                    subtype="api_retry",
                    data={
                        "type": "system",
                        "subtype": "api_retry",
                        "attempt": 1,
                        "max_retries": 10,
                        "retry_delay_ms": 500,
                        "error_status": 401,
                        "error": "authentication_failed",
                    },
                )
            ]

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            # Create a gateway executor that uses a Databricks profile path.
            # gateway=True + no host/base_url overrides → _gateway_uses_databricks_profile is True.
            # Patch _resolve_gateway_env to avoid needing a real ~/.databrickscfg.
            with patch(
                "omnigent.inner.claude_sdk_executor._resolve_gateway_env",
                return_value={
                    "ANTHROPIC_BASE_URL": "https://host/ai-gateway/anthropic",
                    "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "900000",
                    "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
                    "OMNIGENT_CLAUDE_API_KEY_HELPER": "databricks auth token ...",
                },
            ):
                executor = ClaudeSDKExecutor(gateway=True)
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hello"}],
                        [],
                        "",
                    )
                ]
            self.assertEqual(len(events), 1)
            self.assertIsInstance(events[0], ExecutorError)
            self.assertIn("authentication failed", events[0].message)
            # Databricks gateway should mention databrickscfg
            self.assertIn("databrickscfg", events[0].remediation or "")

        _run(_t())


# ---------------------------------------------------------------------------
# Tests: skills_filter → SDK skills option translation + plugin manifest
# ---------------------------------------------------------------------------


class TestSkillsFilterTranslation(unittest.TestCase):
    """
    Pin the mapping from the spec's ``skills_filter`` to the
    Claude Agent SDK's ``skills`` option.

    The filter has three meaningful values; getting any of them
    wrong silently changes which user / project / bundled skills
    the model sees. This is the seam between AGENTSPEC.md's YAML
    ``skills:`` field and the SDK's documented ``skills`` knob.
    """

    def test_all_lets_sdk_default_setting_sources(self) -> None:
        """
        ``"all"`` → SDK ``skills="all"`` and
        ``setting_sources=None`` (the SDK's default-derivation
        kicks in, producing ``["user", "project"]``).

        Claim: setting_sources is ``None`` (not ``[]``), letting
        the SDK fill it in. A regression that hardcoded an
        explicit list here would freeze the default and miss
        future SDK changes.
        """
        from omnigent.inner.claude_sdk_executor import _resolve_skills_option

        result = _resolve_skills_option("all")
        assert result is not None
        self.assertEqual(result.skills, "all")
        self.assertIsNone(result.setting_sources)

    def test_none_zeros_skills_and_setting_sources(self) -> None:
        """
        ``"none"`` → SDK ``skills=[]`` AND
        ``setting_sources=[]``.

        BOTH must be set to truly suppress host skills. The SDK's
        ``_apply_skills_defaults`` auto-fills
        ``setting_sources=["user","project"]`` when ``skills`` is
        non-None — including when ``skills=[]``. That auto-default
        loads ``~/.claude/skills/`` into the system prompt
        listing even though the ``Skill`` tool itself is hidden.
        Forcing ``setting_sources=[]`` is what actually keeps the
        listing empty. The user-reported regression: with only
        ``skills=[]`` set, ``skills: none`` in YAML still showed
        every host skill in the model's output.
        """
        from omnigent.inner.claude_sdk_executor import _resolve_skills_option

        result = _resolve_skills_option("none")
        assert result is not None
        self.assertEqual(result.skills, [])
        self.assertEqual(result.setting_sources, [])

    def test_list_lets_sdk_default_setting_sources(self) -> None:
        """A list of names round-trips and uses the SDK default."""
        from omnigent.inner.claude_sdk_executor import _resolve_skills_option

        result = _resolve_skills_option(["foo", "bar:baz"])
        assert result is not None
        self.assertEqual(result.skills, ["foo", "bar:baz"])
        self.assertIsNone(result.setting_sources)

    def test_unknown_string_returns_none_for_caller_fallback(self) -> None:
        """
        Unknown strings (e.g. malformed config bypass) return
        ``None`` so the caller can fall back to ``"all"``. The
        spec parser already validates, so this is a belt-and-
        suspenders defense at the executor boundary.
        """
        from omnigent.inner.claude_sdk_executor import _resolve_skills_option

        self.assertIsNone(_resolve_skills_option("bogus"))


async def _turn_options(executor, config=None):
    """Return the ``ClaudeAgentOptions`` one turn builds, stopping before the CLI starts."""
    captured = {}

    async def capture_options(sdk, *, session_key, options, model):
        captured["options"] = options
        raise RuntimeError("stop after options built")

    with patch.object(executor, "_get_or_create_client", side_effect=capture_options):
        with pytest.raises(RuntimeError, match="stop after options built"):
            async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], "", config):
                pass
    return captured["options"]


def _default_executor(**kwargs):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    return ClaudeSDKExecutor(**kwargs)


def _databricks_gateway_executor(**kwargs):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.databricks_executor import DatabricksCredentials

    with patch(
        "omnigent.inner.databricks_executor._read_databrickscfg",
        return_value=DatabricksCredentials(
            host="https://example.cloud.databricks.com", token="dapi_test_token"
        ),
    ):
        return ClaudeSDKExecutor(gateway=True, **kwargs)


def _databricks_opus_executor():
    return _databricks_gateway_executor(model="databricks-claude-opus-4-7")


def _databricks_uc_opus_executor():
    return _databricks_gateway_executor(model="system.ai.claude-opus-4-7")


@pytest.mark.parametrize(
    ("settings_text", "expected"),
    [
        (
            '{"env": {"ANTHROPIC_BEDROCK_BASE_URL": "https://gateway.example", "RETRIES": 3}}',
            {"ANTHROPIC_BEDROCK_BASE_URL": "https://gateway.example"},
        ),
        ("{not json", {}),
        ('{"env": ["ANTHROPIC_BEDROCK_BASE_URL"]}', {}),
        (None, {}),
    ],
    ids=["string-entries", "malformed-json", "env-not-object", "missing-file"],
)
def test_claude_user_settings_env_reads_home_settings(
    settings_text: str | None,
    expected: dict[str, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from omnigent.inner.claude_sdk_executor import _claude_user_settings_env

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    if settings_text is not None:
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "settings.json").write_text(settings_text)

    assert _claude_user_settings_env() == expected


@pytest.mark.parametrize(
    ("make_executor", "skills_filter", "expected_base_url"),
    [
        (_default_executor, "none", "https://gateway.example"),
        (_default_executor, "all", None),
        (_databricks_gateway_executor, "none", None),
    ],
    ids=["no-setting-sources", "cli-loads-user-settings", "omnigent-gateway"],
)
async def test_hermetic_turn_carries_user_settings_env_under_omnigent_env(
    make_executor,
    skills_filter: str,
    expected_base_url: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without setting sources the CLI skips user settings, so the executor passes their env."""
    config_dir = tmp_path / "claude-config"
    config_dir.mkdir()
    user_env = {
        "ANTHROPIC_BEDROCK_BASE_URL": "https://gateway.example",
        "CLAUDE_CODE_ENTRYPOINT": "user-settings-entrypoint",
        "CLAUDE_CODE_MAX_OUTPUT_TOKENS": "64000",
    }
    (config_dir / "settings.json").write_text(json.dumps({"env": user_env}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("OMNIGENT_CLAUDE_CODE_ENTRYPOINT", "omnigent-entrypoint")
    executor = make_executor(skills_filter=skills_filter)

    options = await _turn_options(executor, ExecutorConfig(extra={"max_tokens": 32}))

    assert options.env.get("ANTHROPIC_BEDROCK_BASE_URL") == expected_base_url
    assert options.env["CLAUDE_CODE_ENTRYPOINT"] == "omnigent-entrypoint"
    assert options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == "32"


async def test_hermetic_turn_reads_relative_config_dir_from_cli_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    (workspace / "claude-config").mkdir(parents=True)
    (workspace / "claude-config" / "settings.json").write_text(
        json.dumps({"env": {"ANTHROPIC_BEDROCK_BASE_URL": "https://gateway.example"}})
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "claude-config")
    executor = _default_executor(skills_filter="none", cwd=str(workspace))

    options = await _turn_options(executor)

    assert options.env.get("ANTHROPIC_BEDROCK_BASE_URL") == "https://gateway.example"


@pytest.mark.parametrize(
    ("make_executor", "max_tokens", "expected_thinking"),
    [
        (_default_executor, 32, {"type": "disabled"}),
        (_databricks_opus_executor, 32, {"type": "disabled"}),
        (_default_executor, 1024, {"type": "disabled"}),
        (_default_executor, 1025, None),
        (_databricks_opus_executor, 32000, {"type": "adaptive", "display": "summarized"}),
        (_databricks_uc_opus_executor, 32000, {"type": "adaptive", "display": "summarized"}),
    ],
    ids=[
        "title-cap",
        "title-cap-adaptive-model",
        "largest-cap-without-room",
        "smallest-cap-with-room",
        "large-cap-adaptive-model",
        "large-cap-uc-adaptive-model",
    ],
)
async def test_output_token_cap_reaches_cli_and_keeps_thinking_when_a_budget_fits(
    make_executor, max_tokens: int, expected_thinking: dict[str, str] | None
) -> None:
    options = await _turn_options(
        make_executor(), ExecutorConfig(extra={"max_tokens": max_tokens})
    )

    assert options.env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] == str(max_tokens)
    assert options.thinking == expected_thinking


async def test_retry_policy_reaches_cli_options() -> None:
    from omnigent.spec.types import RetryPolicy

    options = await _turn_options(
        _default_executor(retry_policy=RetryPolicy(max_retries=2, timeout_per_request_s=45.5))
    )

    assert options.env["CLAUDE_CODE_MAX_RETRIES"] == "2"
    assert options.env["API_TIMEOUT_MS"] == "45500"
    assert "ANTHROPIC_MAX_RETRIES" not in options.env
    assert "ANTHROPIC_REQUEST_TIMEOUT_SECONDS" not in options.env


async def test_turn_without_output_cap_keeps_cli_defaults() -> None:
    options = await _turn_options(_default_executor())

    assert "CLAUDE_CODE_MAX_OUTPUT_TOKENS" not in options.env
    assert options.thinking is None


# ---------------------------------------------------------------------------
# Tests: Bundle plugin gating (skill-less bundles emit no --plugin-dir)
# ---------------------------------------------------------------------------


class TestBundlePluginGating(unittest.TestCase):
    def _plugins_for_bundle(self, bundle_dir):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        executor = ClaudeSDKExecutor(
            gateway=True,
            gateway_host="https://gateway.example.com",
            base_url_override="https://gateway.example.com/v1",
            gateway_auth_command="printf token",
            bundle_dir=bundle_dir,
            agent_name="my-agent",
        )

        captured: dict[str, object] = {}

        async def fake_get_or_create_client(sdk, *, session_key, options, model):
            captured["plugins"] = getattr(options, "plugins", None)
            raise RuntimeError("stop after options built")

        async def _t():
            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

        _run(_t())
        return captured["plugins"]

    def test_skill_less_bundle_emits_no_plugin(self):
        # No `skills/` directory -> empty `plugins` and no manifest written
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            self.assertEqual(self._plugins_for_bundle(bundle), [])
            self.assertFalse((bundle / ".claude-plugin" / "plugin.json").exists())

    def test_bundle_with_skills_registers_plugin(self):
        # `skills/` directory -> local plugin for bundle and manifest written
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            skill_dir = bundle / "skills" / "demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text("# demo\n")
            self.assertEqual(
                self._plugins_for_bundle(bundle),
                [{"type": "local", "path": str(bundle)}],
            )
            self.assertTrue((bundle / ".claude-plugin" / "plugin.json").exists())


# ---------------------------------------------------------------------------
# Tests: StreamEvent-based streaming
# ---------------------------------------------------------------------------


class TestStreamEventStreaming(unittest.TestCase):
    def test_live_clients_are_reused_per_omnigent_session(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        query_calls = []
        connect_calls = []

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types()):
            ResultMessage = _ResultMessage
            messages = []

            class ClaudeSDKClient(_SDKClient):
                async def connect(self):
                    connect_calls.append(self)
                    return

                async def query(self, prompt, session_id="default"):
                    query_calls.append(
                        {
                            "prompt": prompt,
                            "session_id": session_id,
                            "extra_args": getattr(self.options, "extra_args", {}),
                            "tools": getattr(self.options, "tools", None),
                            "allowed_tools": getattr(self.options, "allowed_tools", None),
                            "env": getattr(self.options, "env", None),
                        }
                    )
                    result_session_id = (
                        session_id
                        if str(session_id).startswith("claude-")
                        else f"claude-{session_id}"
                    )
                    _FakeSDK.messages = [_ResultMessage(result_session_id, f"result for {prompt}")]

                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                session_a = [{"role": "user", "content": "hello", "session_id": "session-a"}]
                session_b = [{"role": "user", "content": "bonjour", "session_id": "session-b"}]

                events_a1 = [e async for e in executor.run_turn(session_a, [], "")]
                events_b1 = [e async for e in executor.run_turn(session_b, [], "")]
                events_a2 = [e async for e in executor.run_turn(session_a, [], "")]

            self.assertEqual(query_calls[0]["session_id"], "session-a")
            # ``--bare`` was previously included to suppress host config
            # leakage. It was dropped because bare mode also kills
            # CLAUDE.md auto-discovery, plugin sync, and skill loading —
            # which the spec's ``skills:`` field is the proper knob for.
            self.assertEqual(
                query_calls[0]["extra_args"],
                {"no-session-persistence": None},
            )
            # Skill remains available for configured skills; ToolSearch
            # keeps large MCP definitions deferred until they are needed.
            self.assertEqual(query_calls[0]["tools"], ["Skill", "ToolSearch"])
            self.assertEqual(query_calls[0]["env"]["ENABLE_TOOL_SEARCH"], "true")
            self.assertEqual(query_calls[0]["allowed_tools"], [])
            self.assertEqual(query_calls[1]["session_id"], "session-b")
            self.assertEqual(query_calls[2]["session_id"], "session-a")
            self.assertEqual(len(connect_calls), 2)
            self.assertEqual(len(executor._clients), 2)
            self.assertEqual(events_a1[-1].response, "result for hello")
            self.assertEqual(events_b1[-1].response, "result for bonjour")
            self.assertEqual(events_a2[-1].response, "result for hello")

        _run(_t())

    def test_prompt_preset_preserves_instructions_and_tool_restrictions(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
        from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

        captured_options = {}

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types(), _SDKTools):
            ResultMessage = _ResultMessage
            messages = []

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    captured_options["tools"] = getattr(options, "tools", None)
                    captured_options["allowed_tools"] = getattr(options, "allowed_tools", None)
                    captured_options["system_prompt"] = options.system_prompt

                async def query(self, prompt, session_id="default"):
                    _FakeSDK.messages = [_ResultMessage(session_id, "done")]

                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t(preset):
            # Explicit ``sandbox=none`` so the test runs on any
            # platform. The default ``OSEnvSandboxSpec.type`` is
            # ``"linux_bwrap"``; without this override,
            # ``resolve_sandbox`` calls into the bwrap backend and
            # raises on macOS even though the test isn't exercising
            # sandbox behavior.
            executor = ClaudeSDKExecutor(
                system_prompt_preset=preset,
                os_env=OSEnvSpec(
                    type="caller_process",
                    sandbox=OSEnvSandboxSpec(type="none"),
                ),
            )
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hi", "session_id": "session-a"}],
                        [
                            {
                                "name": "sleep",
                                "description": "sleep",
                                "parameters": {"type": "object"},
                            }
                        ],
                        "Resolve this bug.",
                    )
                ]
            # OS operations route through sys_os_* MCP tools, not SDK
            # built-ins. Skill and ToolSearch do not widen OS access.
            self.assertEqual(captured_options["tools"], ["Skill", "ToolSearch"])
            self.assertIn("mcp__omnigent__sleep", captured_options["allowed_tools"])
            self.assertNotIn("Bash", captured_options["allowed_tools"])
            self.assertIsInstance(events[-1], TurnComplete)
            prompt = captured_options["system_prompt"]
            if preset:
                self.assertEqual(prompt["type"], "preset")
                self.assertEqual(prompt["preset"], "claude_code")
                prompt = prompt["append"]
            self.assertTrue(prompt.startswith("Resolve this bug."))
            self.assertIn("mcp__omnigent__<tool_name>", prompt)

        for preset in (None, "claude_code"):
            with self.subTest(preset=preset):
                _run(_t(preset))

        with self.assertRaisesRegex(ValueError, "system_prompt_preset"):
            ClaudeSDKExecutor(system_prompt_preset="unknown")

    def test_mcp_only_session_keeps_discovery_tools_without_native_os_tools(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        captured_options = {}

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types(), _SDKTools):
            ResultMessage = _ResultMessage
            messages = []

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    captured_options["tools"] = getattr(options, "tools", None)
                    captured_options["allowed_tools"] = getattr(options, "allowed_tools", None)

                async def query(self, prompt, session_id="default"):
                    _FakeSDK.messages = [_ResultMessage(session_id, "done")]

                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hi", "session_id": "session-a"}],
                        [
                            {
                                "name": "sleep",
                                "description": "sleep",
                                "parameters": {"type": "object"},
                            }
                        ],
                        "",
                    )
                ]
            # Default ``skills_filter="all"`` exposes the ``Skill`` tool
            # through the Claude SDK plugin mechanism. ToolSearch defers
            # MCP definitions until needed. The OS tools
            # (Bash/Read/Edit/Write/Glob/Grep) stay absent — that's
            # what this test pins. Neither base tool widens the FS attack
            # surface.
            self.assertEqual(captured_options["tools"], ["Skill", "ToolSearch"])
            self.assertEqual(captured_options["allowed_tools"], ["mcp__omnigent__sleep"])
            self.assertIsInstance(events[-1], TurnComplete)

        _run(_t())

    def test_session_send_tool_is_exposed_via_mcp(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        captured_options = {}

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types(), _SDKTools):
            ResultMessage = _ResultMessage
            messages = []

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    captured_options["allowed_tools"] = getattr(options, "allowed_tools", None)
                    captured_options["system_prompt"] = getattr(options, "system_prompt", None)

                async def query(self, prompt, session_id="default"):
                    _FakeSDK.messages = [_ResultMessage(session_id, "done")]

                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hi", "session_id": "session-a"}],
                        [
                            {
                                "name": "sys_session_send",
                                "description": "Send into session",
                                "parameters": {
                                    "type": "object",
                                    "properties": {
                                        "tool": {"type": "string"},
                                        "session": {"type": "string"},
                                        "args": {"type": "object"},
                                    },
                                },
                            }
                        ],
                        "Delegate through `sys_session_send`.",
                    )
                ]
            self.assertIn("mcp__omnigent__sys_session_send", captured_options["allowed_tools"])
            self.assertIn(
                "use `mcp__omnigent__sys_session_send` when instructions say `sys_session_send`",
                captured_options["system_prompt"],
            )
            self.assertIsInstance(events[-1], TurnComplete)

        _run(_t())

    def test_session_rename_tool_uses_exact_sdk_mcp_name(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        captured_options = {}

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types(), _SDKTools):
            ResultMessage = _ResultMessage
            messages = []

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    captured_options["allowed_tools"] = getattr(options, "allowed_tools", None)
                    captured_options["system_prompt"] = getattr(options, "system_prompt", None)

                async def query(self, prompt, session_id="default"):
                    _FakeSDK.messages = [_ResultMessage(session_id, "done")]

                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    event
                    async for event in executor.run_turn(
                        [{"role": "user", "content": "hi", "session_id": "session-a"}],
                        [
                            {
                                "name": "sys_session_rename",
                                "description": "Rename current session",
                                "parameters": {
                                    "type": "object",
                                    "properties": {"title": {"type": "string"}},
                                    "required": ["title"],
                                },
                            }
                        ],
                        "Call `sys_session_rename` before replying.",
                    )
                ]
            self.assertIn(
                "mcp__omnigent__sys_session_rename",
                captured_options["allowed_tools"],
            )
            self.assertIn(
                "use `mcp__omnigent__sys_session_rename` when instructions say "
                "`sys_session_rename`",
                captured_options["system_prompt"],
            )
            self.assertIsInstance(events[-1], TurnComplete)

        _run(_t())

    def test_crashed_session_refuses_future_turns(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _FakeSDK(_sdk_types()):
            class ClaudeSDKClient(_SDKClient):
                async def query(self, prompt, session_id="default"):
                    raise RuntimeError("claude subprocess crashed")

                async def receive_response(self):
                    if False:
                        yield None

        async def _t():
            executor = ClaudeSDKExecutor()
            messages = [{"role": "user", "content": "hello", "session_id": "session-a"}]
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                first_events = [e async for e in executor.run_turn(messages, [], "")]
                second_events = [e async for e in executor.run_turn(messages, [], "")]

            self.assertIsInstance(first_events[0], ExecutorError)
            self.assertIn("claude subprocess crashed", first_events[0].message)
            self.assertIsInstance(second_events[0], ExecutorError)
            self.assertIn("cannot continue in this Session", second_events[0].message)
            self.assertIn("claude subprocess crashed", second_events[0].message)
            self.assertIn("session-a", executor._crashed_sessions)

        _run(_t())

    def test_cancelled_turn_evicts_wedged_client(self):
        """A cancelled turn evicts the cached client so resume can recover (#2109).

        ``asyncio.CancelledError`` is a ``BaseException``, so the idle-watchdog
        cancel bypasses run_turn's ``except Exception`` boundary and the
        wedged client used to stay cached.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        created = []
        wedge_reached = asyncio.Event()

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK(_sdk_types()):
            ResultMessage = _ResultMessage

            class ClaudeSDKClient(_SDKClient):
                def __init__(self, options):
                    self.options = options
                    self.index = len(created)
                    created.append(self)

                async def receive_response(self):
                    if self.index == 0:
                        # First client wedges like a stuck tool: no events.
                        wedge_reached.set()
                        await asyncio.Event().wait()
                    yield _ResultMessage("claude-session-a", "recovered")

        async def _t():
            executor = ClaudeSDKExecutor()
            messages = [{"role": "user", "content": "hello", "session_id": "session-a"}]
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):

                async def _consume():
                    return [e async for e in executor.run_turn(messages, [], "")]

                turn = asyncio.ensure_future(_consume())
                await asyncio.wait_for(wedge_reached.wait(), timeout=5)
                turn.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await turn

                # Evicted without a crash mark so the next turn rebuilds
                # a fresh client.
                self.assertEqual(executor._clients, {})
                self.assertNotIn("session-a", executor._crashed_sessions)

                events = [e async for e in executor.run_turn(messages, [], "")]

            self.assertEqual(len(created), 2)
            self.assertIsInstance(events[-1], TurnComplete)
            self.assertEqual(events[-1].response, "recovered")

        _run(_t())

    def test_close_session_disconnects_live_client(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ClaudeClientState

        disconnect = AsyncMock()
        client = type("Client", (), {"disconnect": disconnect})()

        async def _t():
            executor = ClaudeSDKExecutor()
            executor._clients["session-a"] = _ClaudeClientState(client=client, model=None)
            await executor.close_session("session-a")
            disconnect.assert_awaited_once_with()
            self.assertEqual(executor._clients, {})

        _run(_t())

    def test_interrupt_session_interrupts_then_drops_session(self):
        """A user interrupt fires a safe interrupt, then drops the session.

        ``run_turn`` decides whether to resume via
        ``session_key in self._clients``. Dropping the session after an
        interrupt is what forces the next turn to rebuild from full
        history (with the runner's ``[System: interrupted]`` marker)
        instead of resuming a live session whose transcript still holds
        the abandoned prompt. If ``_clients`` were left populated, the
        next turn would resume and silently continue the canceled
        instruction.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ClaudeClientState

        interrupt = AsyncMock()
        disconnect = AsyncMock()
        client = type("Client", (), {"interrupt": interrupt, "disconnect": disconnect})()

        async def _t():
            executor = ClaudeSDKExecutor()
            executor._clients["session-a"] = _ClaudeClientState(client=client, model=None)

            interrupted = await executor.interrupt_session("session-a")

            self.assertTrue(interrupted)
            # Safe interrupt is attempted first to halt the in-flight turn.
            interrupt.assert_awaited_once_with()
            # Then the session is torn down (disconnect) and removed from
            # _clients so the next turn cannot resume it. An empty dict here
            # is the invariant that prevents the canceled-instruction leak.
            disconnect.assert_awaited_once_with()
            self.assertEqual(executor._clients, {})

        _run(_t())

    def test_interrupt_session_closes_even_when_interrupt_fails(self):
        """A failed safe interrupt still drops the session.

        The session must be torn down regardless of whether the SDK's
        ``interrupt()`` succeeds — otherwise a flaky interrupt would
        leave the abandoned-prompt session resumable. If ``close_session``
        is not awaited here, the interrupt-failure path leaks the session.
        """
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ClaudeClientState

        async def fail_interrupt():
            raise RuntimeError("boom")

        client = type("Client", (), {"interrupt": fail_interrupt})()

        async def _t():
            executor = ClaudeSDKExecutor()
            executor._clients["session-a"] = _ClaudeClientState(client=client, model=None)
            with patch.object(executor, "close_session", new=AsyncMock()) as close_session:
                interrupted = await executor.interrupt_session("session-a")

            self.assertTrue(interrupted)
            close_session.assert_awaited_once_with("session-a")

        _run(_t())

    def test_close_disconnects_all_live_clients(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ClaudeClientState

        disconnect_a = AsyncMock()
        disconnect_b = AsyncMock()
        client_a = type("Client", (), {"disconnect": disconnect_a})()
        client_b = type("Client", (), {"disconnect": disconnect_b})()

        async def _t():
            executor = ClaudeSDKExecutor()
            executor._clients["session-a"] = _ClaudeClientState(client=client_a, model=None)
            executor._clients["session-b"] = _ClaudeClientState(client=client_b, model=None)
            await executor.close()
            disconnect_a.assert_awaited_once_with()
            disconnect_b.assert_awaited_once_with()
            self.assertEqual(executor._clients, {})

        _run(_t())

    def test_close_session_force_closes_on_loop_mismatch(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor, _ClaudeClientState

        client = type("Client", (), {})()
        client.disconnect = AsyncMock()

        async def _t():
            executor = ClaudeSDKExecutor()
            executor._clients["session-a"] = _ClaudeClientState(
                client=client,
                model=None,
                loop=object(),
                task=None,
            )
            with patch.object(executor, "_force_close_client", new=AsyncMock()) as force_close:
                await executor.close_session("session-a")
            client.disconnect.assert_not_awaited()
            force_close.assert_awaited_once_with(client)
            self.assertEqual(executor._clients, {})

        _run(_t())

    def test_text_deltas_yield_text_chunks(self):
        from claude_agent_sdk.types import (
            ClaudeAgentOptions as SDKClaudeAgentOptions,
        )
        from claude_agent_sdk.types import (
            ResultMessage as SDKResultMessage,
        )
        from claude_agent_sdk.types import (
            StreamEvent as SDKStreamEvent,
        )

        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _Sentinel:
            pass

        class _FakeSDK(_sdk_types()):
            AssistantMessage = _Sentinel
            UserMessage = _Sentinel
            SystemMessage = _Sentinel
            StreamEvent = SDKStreamEvent
            ResultMessage = SDKResultMessage
            ClaudeAgentOptions = SDKClaudeAgentOptions
            messages = [
                SDKStreamEvent(
                    uuid="u1",
                    session_id="s1",
                    event={
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": "Hello"},
                    },
                ),
                SDKStreamEvent(
                    uuid="u2",
                    session_id="s1",
                    event={
                        "type": "content_block_delta",
                        "index": 0,
                        "delta": {"type": "text_delta", "text": " world"},
                    },
                ),
                SDKResultMessage(
                    subtype="result",
                    session_id="s1",
                    result="Hello world",
                    total_cost_usd=0.0,
                    duration_ms=100,
                    duration_api_ms=80,
                    is_error=False,
                    num_turns=1,
                ),
            ]

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "hi"}],
                        [],
                        "",
                    )
                ]
            chunks = [e for e in events if isinstance(e, TextChunk)]
            self.assertEqual(len(chunks), 2)
            self.assertEqual(chunks[0].text, "Hello")
            self.assertEqual(chunks[1].text, " world")
            self.assertIsInstance(events[-1], TurnComplete)
            self.assertEqual(events[-1].response, "Hello world")

        _run(_t())

    def test_tool_use_assembly_yields_tool_call_request_with_args(self):
        """
        A streaming turn that contains a ``content_block_start`` tool_use
        event plus a subsequent ``AssistantMessage`` with the assembled
        ``ToolUseBlock.input`` must yield exactly one
        :class:`ToolCallRequest` carrying the assembled args.

        Regression pin: the streaming path used to emit
        ``ToolCallRequest(name=..., args={})`` at ``content_block_start``,
        before Claude had streamed the ``input_json_delta`` events. The
        REPL then rendered tool calls as ``⏵ Bash()`` with no visible
        command because the args summary saw an empty dict. The fix
        defers the emission to the ``AssistantMessage`` branch where
        ``tool_block.input`` is populated.

        The test fails pre-fix at the args assertion below:
        ``reqs[0].args`` is ``{}``, not ``{"command": "ls -la"}``.
        """
        # Real types from the SDK so the production
        # ``isinstance(message, sdk.AssistantMessage)`` and
        # ``isinstance(block, sdk.ToolUseBlock)`` checks fire. A
        # MagicMock / _Sentinel would silently bypass both branches
        # and the test would pass vacuously with zero emissions.
        from claude_agent_sdk.types import (
            AssistantMessage as SDKAssistantMessage,
        )
        from claude_agent_sdk.types import (
            ClaudeAgentOptions as SDKClaudeAgentOptions,
        )
        from claude_agent_sdk.types import (
            ResultMessage as SDKResultMessage,
        )
        from claude_agent_sdk.types import (
            StreamEvent as SDKStreamEvent,
        )
        from claude_agent_sdk.types import (
            ToolUseBlock as SDKToolUseBlock,
        )

        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _Sentinel:
            pass

        class _FakeSDK(_sdk_types()):
            AssistantMessage = SDKAssistantMessage
            UserMessage = _Sentinel
            SystemMessage = _Sentinel
            StreamEvent = SDKStreamEvent
            ResultMessage = SDKResultMessage
            ClaudeAgentOptions = SDKClaudeAgentOptions
            TextBlock = _Sentinel
            ThinkingBlock = _Sentinel
            ToolUseBlock = SDKToolUseBlock
            ToolResultBlock = _Sentinel
            messages = [
                # Live SDK order: tool_use block_start fires before
                # Claude has streamed the full ``input_json_delta``
                # sequence. The production path now only tracks the
                # tool id here — it does NOT emit ToolCallRequest
                # yet. Keeping this event in the fixture ensures a
                # future regression that re-introduces the early
                # emission fails the ``len(reqs) == 1`` check below.
                SDKStreamEvent(
                    uuid="u1",
                    session_id="s1",
                    event={
                        "type": "content_block_start",
                        "index": 0,
                        "content_block": {
                            "type": "tool_use",
                            "id": "tool_1",
                            "name": "Bash",
                            "input": {},
                        },
                    },
                ),
                # Full AssistantMessage after input deltas have
                # assembled — this is where ``tool_block.input`` is
                # populated and the ToolCallRequest must fire.
                SDKAssistantMessage(
                    content=[
                        SDKToolUseBlock(
                            id="tool_1",
                            name="Bash",
                            input={"command": "ls -la"},
                        ),
                    ],
                    model="claude-sonnet-4",
                ),
                SDKResultMessage(
                    subtype="result",
                    session_id="s1",
                    result="",
                    total_cost_usd=0.0,
                    duration_ms=100,
                    duration_api_ms=80,
                    is_error=False,
                    num_turns=1,
                ),
            ]

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "run ls"}],
                        [],
                        "",
                    )
                ]
            reqs = [e for e in events if isinstance(e, ToolCallRequest)]
            # 1 = exactly one emission. A value of 2 would mean the
            # early (empty-args) emission was re-introduced alongside
            # the AssistantMessage one; 0 would mean the new path
            # silently dropped the emission.
            self.assertEqual(len(reqs), 1)
            self.assertEqual(reqs[0].name, "Bash")
            # The specific regression: args must be the assembled dict
            # from ``tool_block.input``, not ``{}``. Pre-fix this was
            # ``{}`` and downstream rendered ``⏵ Bash()``.
            self.assertEqual(reqs[0].args, {"command": "ls -la"})

        _run(_t())

    def test_tool_result_error_yields_tool_call_complete_error(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _ToolUseBlock:
            def __init__(self, id, name, input):
                self.id = id
                self.name = name
                self.input = input

        class _ToolResultBlock:
            def __init__(self, tool_use_id, content, is_error):
                self.tool_use_id = tool_use_id
                self.content = content
                self.is_error = is_error

        class _AssistantMessage:
            def __init__(self, content):
                self.content = content

        class _UserMessage:
            def __init__(self, content):
                self.content = content

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK:
            AssistantMessage = _AssistantMessage
            UserMessage = _UserMessage
            SystemMessage = type("SystemMessage", (), {})
            ResultMessage = _ResultMessage
            ToolUseBlock = _ToolUseBlock
            ToolResultBlock = _ToolResultBlock
            TextBlock = type("TextBlock", (), {})
            ThinkingBlock = type("ThinkingBlock", (), {})
            ClaudeAgentOptions = type(
                "ClaudeAgentOptions",
                (),
                {"__init__": lambda self, **kwargs: self.__dict__.update(kwargs)},
            )
            messages = [
                _AssistantMessage([_ToolUseBlock("tool_1", "fail", {})]),
                _UserMessage(
                    [
                        _ToolResultBlock(
                            "tool_1",
                            [{"type": "text", "text": '{"error": "boom"}'}],
                            True,
                        )
                    ]
                ),
                _ResultMessage("s1", "done"),
            ]

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "run fail"}],
                        [],
                        "",
                    )
                ]
            tool_events = [e for e in events if isinstance(e, ToolCallComplete)]
            self.assertEqual(len(tool_events), 1)
            self.assertEqual(tool_events[0].status, ToolCallStatus.ERROR)
            self.assertEqual(tool_events[0].error, "boom")

        _run(_t())

    def test_tool_result_blocked_yields_blocked_status(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        class _ToolUseBlock:
            def __init__(self, id, name, input):
                self.id = id
                self.name = name
                self.input = input

        class _ToolResultBlock:
            def __init__(self, tool_use_id, content, is_error):
                self.tool_use_id = tool_use_id
                self.content = content
                self.is_error = is_error

        class _AssistantMessage:
            def __init__(self, content):
                self.content = content

        class _UserMessage:
            def __init__(self, content):
                self.content = content

        class _ResultMessage:
            def __init__(self, session_id, result):
                self.session_id = session_id
                self.result = result

        class _FakeSDK:
            AssistantMessage = _AssistantMessage
            UserMessage = _UserMessage
            SystemMessage = type("SystemMessage", (), {})
            ResultMessage = _ResultMessage
            ToolUseBlock = _ToolUseBlock
            ToolResultBlock = _ToolResultBlock
            TextBlock = type("TextBlock", (), {})
            ThinkingBlock = type("ThinkingBlock", (), {})
            ClaudeAgentOptions = type(
                "ClaudeAgentOptions",
                (),
                {"__init__": lambda self, **kwargs: self.__dict__.update(kwargs)},
            )
            messages = [
                _AssistantMessage([_ToolUseBlock("tool_1", "blocked_tool", {})]),
                _UserMessage(
                    [
                        _ToolResultBlock(
                            "tool_1",
                            [{"type": "text", "text": '{"blocked": true, "reason": "Nope"}'}],
                            True,
                        )
                    ]
                ),
                _ResultMessage("s1", "done"),
            ]

            class ClaudeSDKClient(_SDKClient):
                async def receive_response(self):
                    for message in _FakeSDK.messages:
                        yield message

        async def _t():
            executor = ClaudeSDKExecutor()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
                events = [
                    e
                    async for e in executor.run_turn(
                        [{"role": "user", "content": "run blocked"}],
                        [],
                        "",
                    )
                ]
            tool_events = [e for e in events if isinstance(e, ToolCallComplete)]
            self.assertEqual(len(tool_events), 1)
            self.assertEqual(tool_events[0].status, ToolCallStatus.BLOCKED)
            self.assertEqual(tool_events[0].error, "Nope")

        _run(_t())


# ---------------------------------------------------------------------------
# Tests: _unset_env_var context manager
# ---------------------------------------------------------------------------


def test_unset_env_var_removes_and_restores(monkeypatch):
    """Env var present before ``with`` is absent during, restored after."""
    from omnigent.inner.claude_sdk_executor import _unset_env_var

    monkeypatch.setenv("CLAUDECODE", "parent-value")
    with _unset_env_var("CLAUDECODE"):
        assert "CLAUDECODE" not in os.environ
    assert os.environ["CLAUDECODE"] == "parent-value"


def test_unset_env_var_noop_when_unset(monkeypatch):
    """When env var is not set before ``with``, block runs cleanly and key stays unset."""
    from omnigent.inner.claude_sdk_executor import _unset_env_var

    monkeypatch.delenv("CLAUDECODE", raising=False)
    with _unset_env_var("CLAUDECODE"):
        assert "CLAUDECODE" not in os.environ
    assert "CLAUDECODE" not in os.environ


def test_unset_env_var_restores_on_exception(monkeypatch):
    """Restoration must still happen when the block raises."""
    from omnigent.inner.claude_sdk_executor import _unset_env_var

    monkeypatch.setenv("CLAUDECODE", "original")
    with pytest.raises(RuntimeError, match="boom"):
        with _unset_env_var("CLAUDECODE"):
            assert "CLAUDECODE" not in os.environ
            raise RuntimeError("boom")
    assert os.environ["CLAUDECODE"] == "original"


def test_databricks_model_without_routing_raises() -> None:
    """``databricks-*`` model with ``gateway=False`` raises ``ValueError``.

    Without the guard the executor silently hits ``api.anthropic.com``
    and surfaces a confusing "model not found" error.
    """
    import pytest

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    with pytest.raises(ValueError, match="Databricks-hosted model"):
        ClaudeSDKExecutor(
            model="databricks-claude-sonnet-4-6",
            gateway=False,
        )


def test_non_databricks_model_without_routing_does_not_raise() -> None:
    """Non-``databricks-*`` model with ``gateway=False`` must not raise.

    Ensures the guard only fires on the ``databricks-`` prefix.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    executor = ClaudeSDKExecutor(
        model="claude-3-5-sonnet-20241022",
        gateway=False,
    )
    assert not executor._gateway


# ---------------------------------------------------------------------------
# ANTHROPIC_API_KEY stripping during connect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_anthropic_api_key_stripped_during_connect(monkeypatch):
    """``_get_or_create_client`` must strip ``ANTHROPIC_API_KEY`` from
    ``os.environ`` during the ``connect()`` window so the Claude CLI
    uses subscription auth instead of a developer API key.

    This test drives ``_get_or_create_client`` with a stub SDK and
    captures ``os.environ`` at the moment ``connect()`` is invoked,
    ensuring both ``CLAUDECODE`` and ``ANTHROPIC_API_KEY`` are absent.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    # Env snapshot captured inside connect() -- proves the real code
    # path strips the keys, not just a standalone _unset_env_var call.
    connect_env: dict[str, str] = {}

    class _StubClient:
        """Minimal client whose connect() captures os.environ."""

        def __init__(self, options):
            """Store options for protocol compliance.

            :param options: SDK options object (unused by stub).
            """
            self.options = options
            self._query = None
            self._transport = None

        async def connect(self) -> None:
            """Record env state at the moment the real code calls connect."""
            connect_env.update(os.environ)

        async def disconnect(self) -> None:
            """No-op disconnect."""

    class _StubSDK:
        """Minimal SDK whose ClaudeSDKClient captures env during connect."""

        ClaudeSDKClient = _StubClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-secret")
    monkeypatch.setenv("CLAUDECODE", "parent-value")

    executor = ClaudeSDKExecutor()
    options = SimpleNamespace()
    await executor._get_or_create_client(
        _StubSDK,  # type: ignore[arg-type]
        session_key="test-session",
        options=options,
        model=None,
    )

    # Both keys must be absent at the moment connect() ran.
    assert "ANTHROPIC_API_KEY" not in connect_env, (
        "ANTHROPIC_API_KEY leaked into connect() -- subscription auth bypassed"
    )
    assert "CLAUDECODE" not in connect_env, (
        "CLAUDECODE leaked into connect() -- nested-session error risk"
    )
    # Both are restored after _get_or_create_client returns.
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-test-secret"
    assert os.environ["CLAUDECODE"] == "parent-value"


@pytest.mark.asyncio
async def test_get_or_create_client_surfaces_cli_stderr_on_connect_timeout(monkeypatch):
    """A connect timeout must include the CLI's stderr tail in the
    raised ``TimeoutError`` so CI logs surface what the subprocess was
    doing while it hung.
    """
    from omnigent.inner import claude_sdk_executor as cse
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    monkeypatch.setattr(cse, "_CONNECT_TIMEOUT_SECONDS", 0.2)

    class _StubClient:
        def __init__(self, options) -> None:
            self.options = options
            # ``_force_close_client`` reads these on the failure path.
            self._query = None
            self._transport = None

        async def connect(self) -> None:
            assert callable(self.options.stderr), (
                "executor must install a stderr callback before connect"
            )
            self.options.stderr("Spawning claude CLI...\n")
            self.options.stderr("ERROR: hanging on auth refresh\n")
            await asyncio.sleep(5.0)

        async def disconnect(self) -> None:
            pass

    class _StubSDK:
        ClaudeSDKClient = _StubClient

    executor = ClaudeSDKExecutor()
    options = SimpleNamespace(stderr=None)

    with pytest.raises(TimeoutError) as excinfo:
        await executor._get_or_create_client(
            _StubSDK,  # type: ignore[arg-type]
            session_key="test-session",
            options=options,
            model=None,
        )

    msg = str(excinfo.value)
    # ``(no CLI stderr captured)`` here means the tee callback was never wired.
    assert "Spawning claude CLI" in msg, msg
    assert "hanging on auth refresh" in msg, msg
    assert "after 0s" in msg
    # ``_tee_stderr`` must be unwired in the finally so the buffer can be
    # GC'd and post-connect stderr flows directly to the original callback.
    assert options.stderr is None


@pytest.mark.asyncio
async def test_mcp_servers_signed_in_mid_session_reconnect_before_the_next_turn(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    status_file = tmp_path / "mcp-auth-status.json"
    monkeypatch.setenv("OMNIGENT_MCP_AUTH_STATUS_FILE", str(status_file))
    reported = dict.fromkeys(
        ("notes", "wiki", "docs", "figjam", "drive", "calendar", "slow", "late"),
        "sign_in_required",
    )
    reported["jira"] = "connected"

    def report(**statuses: str) -> None:
        reported.update(statuses)
        entries = [{"harness": "claude", "name": n, "status": s} for n, s in reported.items()]
        entries.append({"harness": "codex", "name": "codex-docs", "status": "connected"})
        status_file.write_text(json.dumps({"servers": entries}))

    live = {
        "notes": "failed",
        "wiki": "needs-auth",
        "docs": "pending",
        # The CLI names plugin servers ``plugin:<plugin>:<server>``; the host reports ``<server>``.
        "plugin:figma:figjam": "failed",
        "drive": "failed",
        "calendar": "failed",
        "slow": "failed",
        "late": "failed",
        "linear": "connected",
        "jira": "failed",
        "codex-docs": "failed",
    }
    status_reply = "ok"
    fail_once = {"notes"}
    reconnects: list[str] = []
    in_flight: set[str] = set()
    overlapped = False
    reconnect_hung = asyncio.Event()
    fake_sdk = _make_recovery_fake_sdk()

    class _McpClient(fake_sdk.ClaudeSDKClient):
        async def get_mcp_status(self) -> dict[str, object]:
            if status_reply == "error":
                raise RuntimeError("control channel busy")
            if status_reply == "hang":
                await asyncio.Event().wait()
            return {"mcpServers": [{"name": n, "status": s} for n, s in live.items()]}

        async def reconnect_mcp_server(self, server_name: str) -> None:
            nonlocal overlapped
            overlapped = overlapped or bool(in_flight)
            reconnects.append(server_name)
            in_flight.add(server_name)
            try:
                if server_name == "late":
                    reconnect_hung.set()
                    await asyncio.Event().wait()
                await asyncio.sleep(0.3 if server_name in ("drive", "calendar") else 0)
            finally:
                in_flight.discard(server_name)
            if server_name in fail_once:
                fail_once.discard(server_name)
                raise RuntimeError("still unauthorized")
            live[server_name] = "connected"

    fake_sdk.ClaudeSDKClient = _McpClient
    executor = ClaudeSDKExecutor()
    messages: list[dict[str, object]] = []

    async def turn(text: str) -> _McpClient:
        messages.append({"role": "user", "content": text, "session_id": "mcp"})
        events = [event async for event in executor.run_turn(messages, [], "")]
        assert not [event for event in events if isinstance(event, ExecutorError)]
        assert any(isinstance(event, TurnComplete) for event in events)
        messages.append({"role": "assistant", "content": f"answer to {text}"})
        return executor._clients["mcp"].client

    report()
    with (
        patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk),
        patch.object(executor, "_force_close_client", new_callable=AsyncMock) as close,
    ):
        first = await turn("q0")
        assert await turn("q1") is first
        assert reconnects == []

        report(notes="connected", wiki="connected", docs="connected", figjam="connected")
        report(linear="connected")
        status_reply = "error"
        assert await turn("q2") is first
        assert reconnects == []

        # One failed reconnect neither fails the turn nor stops the others.
        status_reply = "ok"
        assert await turn("q3") is first
        assert reconnects == ["notes", "wiki", "plugin:figma:figjam"]
        # The CLI handles control requests one at a time.
        assert not overlapped

        # The failed and still-pending servers are checked again.
        live["docs"] = "failed"
        assert await turn("q4") is first
        assert reconnects[3:] == ["notes", "docs"]
        assert await turn("q5") is first
        assert len(reconnects) == 5

        report(drive="connected", calendar="connected")
        assert await turn("/compact") is first
        assert len(reconnects) == 5

        # Reconnects share one budget. A CLI still busy when it runs out would hold the prompt,
        # so a new one runs it.
        monkeypatch.setattr(
            "omnigent.inner.claude_sdk_executor._MCP_RECONNECT_TIMEOUT_SECONDS", 0.5
        )
        second = await turn("q6")
        assert second is not first
        assert reconnects[5:] == ["drive", "calendar"]
        close.assert_awaited_once_with(first)
        assert "answer to q5" in second.prompts[-1]
        # The new CLI connects every server as it starts.
        assert await turn("q7") is second
        assert len(reconnects) == 7

        report(slow="connected")
        status_reply = "hang"
        monkeypatch.setattr("omnigent.inner.claude_sdk_executor._MCP_STATUS_TIMEOUT_SECONDS", 0.05)
        third = await turn("q8")
        assert third is not second
        assert len(reconnects) == 7
        assert "answer to q7" in third.prompts[-1]

        # A turn cancelled mid-reconnect does not leave the busy CLI for the next turn.
        report(late="connected")
        status_reply = "ok"
        monkeypatch.setattr(
            "omnigent.inner.claude_sdk_executor._MCP_RECONNECT_TIMEOUT_SECONDS", 30
        )
        messages.append({"role": "user", "content": "q9", "session_id": "mcp"})
        reconnect_hung.clear()
        cancelled = asyncio.ensure_future(executor.run_turn(messages, [], "").__anext__())
        await asyncio.wait_for(reconnect_hung.wait(), timeout=5)
        assert reconnects[-1] == "late"
        cancelled.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cancelled
        assert "mcp" not in executor._clients
        await asyncio.gather(*executor._cancel_close_tasks)
        close.assert_awaited_with(third)


def test_resolve_sandbox_cwd_roots_relative_at_runner_workspace(monkeypatch) -> None:
    """A relative ``os_env.cwd`` (notably the default ``"."``) resolves
    against ``OMNIGENT_RUNNER_WORKSPACE`` — not the daemon's process cwd
    — so the sandbox root matches the tmux terminal and never falls back
    to ``$HOME``. Absolute paths keep their root and are resolved by
    ``Path.resolve(strict=False)``."""
    from omnigent.inner.claude_sdk_executor import _resolve_sandbox_cwd

    monkeypatch.setenv("OMNIGENT_RUNNER_WORKSPACE", "/home/bobby/code/agents")
    monkeypatch.chdir("/tmp")

    # ``_resolve_sandbox_cwd`` ends in ``Path.resolve(strict=False)``. On macOS,
    # these literal paths route through firmlinks (``/home`` -> the automounter,
    # ``/tmp`` -> ``/private/tmp``), so compare against the same resolution
    # instead of literal strings. On Linux both sides are identical.
    workspace = Path("/home/bobby/code/agents").resolve(strict=False)
    assert _resolve_sandbox_cwd(".") == workspace
    assert _resolve_sandbox_cwd(None) == workspace
    assert _resolve_sandbox_cwd("src") == (workspace / "src").resolve(strict=False)
    assert _resolve_sandbox_cwd("/etc/foo") == Path("/etc/foo").resolve(strict=False)

    # No workspace set → falls back to the process cwd (prior behavior).
    monkeypatch.delenv("OMNIGENT_RUNNER_WORKSPACE", raising=False)
    assert _resolve_sandbox_cwd(".") == Path("/tmp").resolve(strict=False)


@pytest.mark.parametrize("env_value", ["1", "true", "yes"])
def test_prepare_claude_cli_path_bypasses_wrapper_when_env_set(
    monkeypatch, caplog, env_value: str
) -> None:
    """
    ``OMNIGENT_CLAUDE_SDK_NO_SANDBOX`` (any truthy value) must skip
    ``create_exec_launcher`` and hand back the raw CLI path. Used as a
    diagnostic knob to isolate the sandbox as a cause of the silent
    claude-sdk connect hang on the nightly Linux runner.
    """
    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    monkeypatch.setenv("OMNIGENT_CLAUDE_SDK_NO_SANDBOX", env_value)

    def _fail_if_called(*args, **kwargs) -> str:
        raise AssertionError("create_exec_launcher must not be called when bypass is enabled")

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.create_exec_launcher",
        _fail_if_called,
    )

    spec = OSEnvSpec(
        type="caller_process",
        cwd="/tmp/work",
        sandbox=OSEnvSandboxSpec(
            type="linux_bwrap",
            read_paths=["."],
            write_paths=["."],
            allow_network=True,
        ),
    )
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        prepared = prepare_claude_cli_path("/usr/bin/claude", spec)

    assert prepared.cli_path == "/usr/bin/claude"
    # Bypass keeps native tools off so the diagnostic isolates the
    # CLI-startup variable; matches the fallback shape used when the
    # sandbox can't be applied for other reasons (line 569-574).
    assert prepared.enable_native_tools is False
    # The bypass must be loud in CI: a missing warning means a future
    # diagnostic run could silently fall through without us noticing.
    assert any("Sandbox bypass active" in record.getMessage() for record in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_prepare_tight_cli_process_path_bypasses_wrapper_when_env_set(monkeypatch) -> None:
    """``prepare_tight_cli_process_path`` must also honor the bypass env."""
    from omnigent.inner.claude_sdk_executor import prepare_tight_cli_process_path

    monkeypatch.setenv("OMNIGENT_CLAUDE_SDK_NO_SANDBOX", "1")

    def _fail_if_called(*args, **kwargs) -> str:
        raise AssertionError("create_exec_launcher must not be called when bypass is enabled")

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.create_exec_launcher",
        _fail_if_called,
    )

    assert prepare_tight_cli_process_path("/usr/bin/claude") == "/usr/bin/claude"


def _wrap_probe_spec():
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    return OSEnvSpec(
        type="caller_process",
        cwd="/tmp/work",
        sandbox=OSEnvSandboxSpec(
            type="linux_bwrap",
            read_paths=["."],
            write_paths=["."],
            allow_network=True,
        ),
    )


def _active_policy():
    from omnigent.inner.sandbox import SandboxPolicy

    return SandboxPolicy(
        backend_type="linux_bwrap",
        active=True,
        read_roots=[Path("/tmp/work")],
        write_roots=[Path("/tmp/work")],
        write_files=[],
        allow_network=True,
    )


def test_prepare_claude_cli_path_degrades_when_resolve_sandbox_fails(monkeypatch, caplog) -> None:
    """
    A ``resolve_sandbox`` failure (e.g. ``sandbox-exec`` missing on the
    host) must NOT crash the seat at connect time. The prepare degrades
    to the raw CLI with native tools disabled — the same confinement
    shape as the ``OMNIGENT_CLAUDE_SDK_NO_SANDBOX`` bypass — and warns.
    """
    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path

    def _raise_resolve(*args, **kwargs):
        raise OSError("darwin_seatbelt requires sandbox-exec on PATH")

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.resolve_sandbox", _raise_resolve)

    def _fail_if_called(*args, **kwargs) -> str:
        raise AssertionError("create_exec_launcher must not run when resolve failed")

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.create_exec_launcher", _fail_if_called)

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        prepared = prepare_claude_cli_path("/usr/bin/claude", _wrap_probe_spec())

    assert prepared.cli_path == "/usr/bin/claude"
    assert prepared.enable_native_tools is False
    assert any(
        "Cannot resolve the configured sandbox" in record.getMessage() for record in caplog.records
    ), [r.getMessage() for r in caplog.records]


def test_prepare_claude_cli_path_degrades_when_wrap_probe_fails(monkeypatch, caplog) -> None:
    """
    When the backend can resolve but the spawn-time wrap can't be built
    (un-grantable interpreter layout, profile-size cap, cwd-scan
    overflow), the OSError previously fired inside ``run_launcher`` and
    killed the CLI spawn with an opaque connect timeout. The prepare-
    time probe must catch it and degrade — unwrapped CLI, native tools
    OFF, loud warning — never raise.
    """
    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.resolve_sandbox",
        lambda *a, **k: _active_policy(),
    )

    class _RefusingBackend:
        def wrap_launcher_argv(self, *args, **kwargs):
            raise OSError("would require widening the sandbox read view")

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.get_backend",
        lambda name: _RefusingBackend(),
    )

    def _fail_if_called(*args, **kwargs) -> str:
        raise AssertionError("create_exec_launcher must not run when the wrap probe failed")

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.create_exec_launcher", _fail_if_called)

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        prepared = prepare_claude_cli_path("/usr/bin/claude", _wrap_probe_spec())

    assert prepared.cli_path == "/usr/bin/claude"
    assert prepared.enable_native_tools is False
    assert any("cannot wrap the Claude CLI" in record.getMessage() for record in caplog.records), [
        r.getMessage() for r in caplog.records
    ]


def test_prepare_claude_cli_path_probe_passes_target_and_still_wraps(
    monkeypatch,
) -> None:
    """
    The happy path is unchanged by the probe: the wrap still happens,
    native tools stay ON, and the probe exercises the same lane the
    launcher will (``target=<real CLI>``), so a probe pass means the
    run-time wrap can build the same grants.
    """
    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.resolve_sandbox",
        lambda *a, **k: _active_policy(),
    )

    seen: dict[str, object] = {}

    class _OkBackend:
        def wrap_launcher_argv(self, argv, policy, cwd, chdir=None, target=None):
            seen["target"] = target
            return ["bwrap", "--", *argv]

    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.get_backend",
        lambda name: _OkBackend(),
    )
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.create_exec_launcher",
        lambda path, sandbox: "/tmp/launcher",
    )

    prepared = prepare_claude_cli_path("/usr/bin/claude", _wrap_probe_spec())

    assert prepared.cli_path == "/tmp/launcher"
    assert prepared.enable_native_tools is True
    assert seen["target"] == "/usr/bin/claude", (
        "The probe must exercise the target lane run_launcher will use."
    )


# CORAL(S109): each seatbelt launch gets its own CLI temp dir; no shared temp dir is granted
class _PassingWrapBackend:
    def wrap_launcher_argv(self, argv, policy, cwd, chdir=None, target=None):
        return ["sandbox", "--", *argv]


# CORAL(S113): isolate asks for the private config dir
# CORAL(S115): None takes the default, and seed names the global config copied into it
def _granted_policy(
    monkeypatch, tmp_path: Path, backend_type: str, *, isolate: bool | None = False, seed=None
):
    """The policy the CLI wrap is built from, with HOME, TMPDIR and the socket root in tmp_path."""
    import dataclasses

    from omnigent.inner.claude_sdk_executor import prepare_claude_cli_path

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "tmpdir").mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "tmpdir"))
    monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(tmp_path / "h"))
    policy = dataclasses.replace(_active_policy(), backend_type=backend_type)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.resolve_sandbox", lambda *a, **k: policy
    )
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.get_backend", lambda name: _PassingWrapBackend()
    )
    captured = {}

    def _capture(path, sandbox):
        captured["sandbox"] = sandbox
        return "/tmp/launcher"

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.create_exec_launcher", _capture)
    prepared = prepare_claude_cli_path(
        "/usr/bin/claude", _wrap_probe_spec(), isolate_config=isolate, config_seed=seed
    )
    assert prepared.enable_native_tools is True
    # CORAL(S113, S115): by default every backend but the job object, which confines no files
    default = backend_type != "windows_jobobject"
    assert prepared.config_isolated is (default if isolate is None else isolate)
    return captured["sandbox"]


def _granted_paths(policy) -> list[Path]:
    return [*policy.write_roots, *(policy.read_roots or []), *policy.write_files]


@pytest.mark.parametrize("backend_type", ["darwin_seatbelt", "linux_bwrap"])
def test_prepare_claude_cli_path_grants_no_shared_claude_temp_dir(
    monkeypatch, tmp_path, backend_type: str
) -> None:
    """Neither the runner's ``$TMPDIR/claude-<uid>`` nor ``/tmp/claude-<uid>`` is granted."""
    policy = _granted_policy(monkeypatch, tmp_path, backend_type)

    granted = _granted_paths(policy)
    assert not [path for path in granted if path.name.startswith("claude-")], granted
    assert not (tmp_path / "tmpdir" / f"claude-{os.getuid()}").exists()


def test_prepare_claude_cli_path_gives_each_seatbelt_launch_its_own_cli_temp_dir(
    monkeypatch, tmp_path
) -> None:
    """Seatbelt shares the host's /tmp, so the launcher makes CLAUDE_CODE_TMPDIR per launch."""
    policy = _granted_policy(monkeypatch, tmp_path, "darwin_seatbelt")

    assert policy.launch_tmpdir_env == "CLAUDE_CODE_TMPDIR"
    assert policy.launch_tmpdir_parent == tmp_path / "h"
    # The launcher makes the dir per launch; nothing under the socket root is granted up front.
    assert not [path for path in _granted_paths(policy) if (tmp_path / "h") in path.parents]


def test_prepare_claude_cli_path_leaves_bwraps_private_tmp_alone(monkeypatch, tmp_path) -> None:
    """Bwrap's /tmp is a private tmpfs per launch: no CLI dir is bound over it."""
    policy = _granted_policy(monkeypatch, tmp_path, "linux_bwrap")

    assert (policy.launch_tmpdir_env, policy.launch_tmpdir_parent) == (None, None)


# CORAL(S113): an isolated wrap grants nothing of the user's Claude config home
def _seed_claude_home(home: Path) -> list[Path]:
    """A config home with the two files today's wrap grants; returns what was seeded."""
    (home / ".claude").mkdir(parents=True)
    seeded = [home / ".claude.json", home / ".claude" / ".credentials.json"]
    for path in seeded:
        path.write_text("{}")
    return seeded


def _claude_home_grants(policy, home: Path) -> list[Path]:
    claude_home = (home / ".claude").resolve()
    return [
        path
        for path in _granted_paths(policy)
        if path == (home / ".claude.json").resolve() or path.is_relative_to(claude_home)
    ]


# CORAL(S115): a backend added later is isolated by default too
@pytest.mark.parametrize("backend_type", ["darwin_seatbelt", "linux_bwrap", "a_future_backend"])
@pytest.mark.parametrize("isolate", [True, False, None], ids=["coral", "shared", "default"])
def test_an_isolated_cli_wrap_grants_nothing_of_the_claude_config_home(
    monkeypatch, tmp_path, backend_type: str, isolate: bool | None
) -> None:
    """
    Only ~/.npm/_logs stays, each launch gets CLAUDE_CONFIG_DIR, and ~/.claude is untouched.
    CORAL(S115): the default isolates too, and its seed, not yet written, is the one new read.
    """
    home = tmp_path / "home"
    seeded = _seed_claude_home(home)
    seed = tmp_path / "seed" / "claude.json" if isolate is None else None
    policy = _granted_policy(monkeypatch, tmp_path, backend_type, isolate=isolate, seed=seed)

    grants = _claude_home_grants(policy, home)
    if isolate is not False:
        assert grants == [], grants
        assert sorted((home / ".claude").iterdir()) == seeded[1:]
        assert (home / ".npm" / "_logs").resolve() in policy.write_roots
        assert (policy.scratch_dir_env, policy.scratch_dir_files) == (
            "CLAUDE_CONFIG_DIR",
            ("projects",),
        )
        assert policy.scratch_dir_extra_envs == ("CLAUDE_SECURESTORAGE_CONFIG_DIR",)
        expected = [] if seed is None else [seed.resolve()]
        assert [root for root in policy.read_roots or [] if root.name == "claude.json"] == expected
        assert policy.scratch_dir_seed == tuple((".claude.json", str(path)) for path in expected)
        assert not (tmp_path / "seed").exists()
    else:
        assert len(grants) == 2 * 4 + len(seeded), grants
        assert (policy.scratch_dir_env, policy.scratch_dir_files) == (None, ())


# CORAL(S115): the job object confines no files, so isolating it would only drop the login
def test_a_windows_job_object_cli_keeps_the_shared_claude_config_by_default(
    monkeypatch, tmp_path
) -> None:
    home = tmp_path / "home"
    seeded = _seed_claude_home(home)
    seed = tmp_path / "seed" / "claude.json"
    policy = _granted_policy(monkeypatch, tmp_path, "windows_jobobject", isolate=None, seed=seed)

    assert len(_claude_home_grants(policy, home)) == 2 * 4 + len(seeded)
    assert (policy.scratch_dir_env, policy.scratch_dir_seed) == (None, ())


@pytest.mark.parametrize("isolate", [True, False, None], ids=["coral", "shared", "default"])
def test_an_isolated_tight_cli_wrap_grants_nothing_of_the_claude_config_home(
    monkeypatch, tmp_path, isolate: bool | None
) -> None:
    from omnigent.inner.claude_sdk_executor import prepare_tight_cli_process_path

    home = tmp_path / "home"
    seeded = _seed_claude_home(home)
    seed = tmp_path / "seed" / "claude.json"
    # CORAL(S115): this wrap is always bwrap, so it isolates by default
    options = {"config_seed": seed} if isolate is None else {"isolate_config": isolate}
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.resolve_sandbox", lambda *a, **k: _active_policy()
    )
    captured = {}

    def _capture(path, sandbox):
        captured["sandbox"] = sandbox
        return "/tmp/launcher"

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.create_exec_launcher", _capture)
    assert prepare_tight_cli_process_path("/usr/bin/claude", **options) == "/tmp/launcher"

    policy = captured["sandbox"]
    isolated = isolate is not False  # CORAL(S115): the default isolates
    assert bool(_claude_home_grants(policy, home)) is not isolated
    assert (policy.scratch_dir_env == "CLAUDE_CONFIG_DIR") is isolated
    assert policy.scratch_dir_seed == (
        ((".claude.json", str(seed.resolve())),) if isolate is None else ()
    )
    if isolated:
        assert sorted((home / ".claude").iterdir()) == seeded[1:]


def _break_wrap(monkeypatch, fault: str) -> None:
    """Leave the CLI unwrapped: by the operator's choice, by design, or by a fault."""
    import dataclasses

    if fault == "operator-opt-out":
        monkeypatch.setenv("OMNIGENT_CLAUDE_SDK_NO_SANDBOX", "1")
        return

    def _resolve(spec, cwd):
        if fault == "resolve-fails":
            raise OSError("darwin_seatbelt requires sandbox-exec on PATH")
        allow_network = spec.sandbox.allow_network
        return dataclasses.replace(
            _active_policy(), active=fault != "inactive", allow_network=allow_network
        )

    class _RefusingBackend:
        def wrap_launcher_argv(self, *args, **kwargs):
            raise OSError("would require widening the sandbox read view")

    backend = _RefusingBackend() if fault == "probe-fails" else _PassingWrapBackend()
    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.resolve_sandbox", _resolve)
    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.get_backend", lambda name: backend)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.create_exec_launcher", lambda path, sandbox: "/l"
    )


# Each case's sandbox spec changes, whether the spec asks for a wrap, and whether it wraps.
_WRAP_CASES = {
    "wraps": ({}, True, True),
    "no-os-env": (None, False, False),
    "operator-opt-out": ({}, False, False),
    "sandbox-none": ({"type": "none"}, False, False),
    "network-off": ({"allow_network": False}, False, False),
    "resolve-fails": ({}, True, False),
    "inactive": ({}, True, False),
    "probe-fails": ({}, True, False),
}


@pytest.mark.parametrize("case", list(_WRAP_CASES))
def test_only_a_wrap_fault_leaves_a_requested_wrap_unapplied(monkeypatch, tmp_path, case) -> None:
    """
    The refusal rule and the wrap's early returns name the same by-design cases, so an
    isolated CLI is refused exactly when a fault left it unwrapped.
    """
    import dataclasses

    from omnigent.inner.claude_sdk_executor import (
        _claude_cli_sandbox_requested,
        prepare_claude_cli_path,
    )

    changes, asks, wraps = _WRAP_CASES[case]
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    _break_wrap(monkeypatch, case)
    spec = _wrap_probe_spec()
    if changes is None:
        spec = None
    else:
        spec = dataclasses.replace(spec, sandbox=dataclasses.replace(spec.sandbox, **changes))

    prepared = prepare_claude_cli_path("/usr/bin/claude", spec, isolate_config=True)

    assert _claude_cli_sandbox_requested(spec) is asks
    assert (prepared.cli_path, prepared.config_isolated) == (
        "/l" if wraps else "/usr/bin/claude",
        wraps,
    )
    assert not (tmp_path / "home" / ".claude").exists()


@pytest.mark.parametrize(("parent", "warns"), [("h", False), ("h" * 40, True)])
def test_the_cli_temp_dir_parent_warns_past_the_clis_short_path_limit(
    monkeypatch, tmp_path, caplog, parent: str, warns: bool
) -> None:
    """Past 44 bytes the CLI sends its child-process temp dirs to the shared /tmp."""
    from omnigent.inner.claude_sdk_executor import _claude_launch_tmpdir_parent

    monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", f"/tmp/{parent}")
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        assert _claude_launch_tmpdir_parent() == Path(f"/tmp/{parent}")

    assert any("exceeds 44 bytes" in record.getMessage() for record in caplog.records) is warns


# ---------------------------------------------------------------------------
# Tests: _to_anthropic_content_blocks
# ---------------------------------------------------------------------------


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def test_to_anthropic_content_blocks_pdf_uses_base64_source() -> None:
    """PDF input_file blocks must use ``source.type = "base64"`` — the
    only MIME Anthropic accepts for the base64 document source shape."""
    pdf_data = _b64(b"%PDF-1.4 fake pdf content".decode("latin-1"))
    blocks = [{"type": "input_file", "file_data": f"data:application/pdf;base64,{pdf_data}"}]
    result = _to_anthropic_content_blocks(blocks)
    assert len(result) == 1
    doc = result[0]
    assert doc["type"] == "document"
    assert doc["source"]["type"] == "base64"
    assert doc["source"]["media_type"] == "application/pdf"
    assert doc["source"]["data"] == pdf_data


def test_to_anthropic_content_blocks_markdown_uses_text_source() -> None:
    """Markdown input_file blocks must use ``source.type = "text"`` —
    Anthropic rejects ``base64`` source with non-PDF media types."""
    md_content = "# Hello\n\nThis is markdown."
    md_b64 = _b64(md_content)
    blocks = [{"type": "input_file", "file_data": f"data:text/markdown;base64,{md_b64}"}]
    result = _to_anthropic_content_blocks(blocks)
    assert len(result) == 1
    doc = result[0]
    assert doc["type"] == "document"
    assert doc["source"]["type"] == "text"
    assert doc["source"]["media_type"] == "text/plain"
    assert doc["source"]["data"] == md_content


def test_to_anthropic_content_blocks_plain_text_uses_text_source() -> None:
    """``text/plain`` input_file blocks must also use ``source.type = "text"``."""
    content = "just some plain text"
    b64 = _b64(content)
    blocks = [{"type": "input_file", "file_data": f"data:text/plain;base64,{b64}"}]
    result = _to_anthropic_content_blocks(blocks)
    assert len(result) == 1
    doc = result[0]
    assert doc["type"] == "document"
    assert doc["source"]["type"] == "text"
    assert doc["source"]["media_type"] == "text/plain"
    assert doc["source"]["data"] == content


# ---------------------------------------------------------------------------
# Tests: connect-failure stderr surfacing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_or_create_client_surfaces_cli_stderr_on_connect_error() -> None:
    """A non-timeout connect failure includes captured CLI stderr."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _StubClient:
        def __init__(self, options: object) -> None:
            self._stderr_cb = getattr(options, "stderr", None)
            self._query = None
            self._transport = None

        async def connect(self) -> None:
            if self._stderr_cb is not None:
                self._stderr_cb("unknown option '--no-session-persistence'\n")
            raise RuntimeError("Command failed with exit code 1; Check stderr output for details")

        async def disconnect(self) -> None:
            pass

    class _StubSDK:
        ClaudeSDKClient = _StubClient

    executor = ClaudeSDKExecutor()
    options = type("Opts", (), {"stderr": None})()

    with pytest.raises(RuntimeError) as excinfo:
        await executor._get_or_create_client(
            _StubSDK,  # type: ignore[arg-type]
            session_key="test-session",
            options=options,
            model=None,
        )

    msg = str(excinfo.value)
    assert "unknown option" in msg, (
        f"Stderr not included in connect error.\nExpected 'unknown option' in: {msg!r}"
    )
    assert "Command failed" in msg, msg


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Tests: TurnComplete.usage populated from ResultMessage.usage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_message_usage_populates_turn_complete_usage() -> None:
    """``ResultMessage.usage`` flows through to ``TurnComplete.usage``.

    The claude-sdk executor must extract the provider-reported token counts
    from ``ResultMessage.usage`` and forward them via ``TurnComplete.usage``
    so the REPL context ring and ``/context`` command can display accurate
    per-turn fill without falling back to a local ``count_tokens()`` estimate.

    Regression guard: before this fix the executor yielded
    ``TurnComplete(response=..., usage=None)`` unconditionally, causing the
    context ring to stop updating after the first turn (the idle-event fallback
    only fired when ``host.tokens_used is None``, which was only true on the
    first turn once the local estimate had been set).
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _Sentinel:
        pass

    sdk_result = SDKResultMessage(
        subtype="result",
        session_id="s1",
        result="Hello",
        total_cost_usd=0.0,
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        usage={
            "input_tokens": 500,
            "output_tokens": 200,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 0,
        },
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [sdk_result]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor()
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    turn = next(e for e in events if isinstance(e, TurnComplete))

    # Provider-reported counts must appear verbatim — if this is None the
    # REPL context ring will never update after the first turn for claude-sdk.
    assert turn.usage is not None, (
        "TurnComplete.usage is None — ResultMessage.usage was not captured. "
        "The context ring and /context command will show stale data after "
        "the first turn."
    )

    # input_tokens / output_tokens must come through from ResultMessage.usage
    assert turn.usage["input_tokens"] == 500, (
        f"input_tokens {turn.usage['input_tokens']} != 500 — "
        "ResultMessage.usage['input_tokens'] was not forwarded."
    )
    assert turn.usage["output_tokens"] == 200, (
        f"output_tokens {turn.usage['output_tokens']} != 200 — "
        "ResultMessage.usage['output_tokens'] was not forwarded."
    )

    # total_tokens is computed as input + output so the toolbar ring can
    # use usage["total_tokens"] without also needing individual fields.
    assert turn.usage["total_tokens"] == 700, (
        f"total_tokens {turn.usage['total_tokens']} != 700 (500+200) — "
        "total_tokens must be computed as input_tokens + output_tokens."
    )

    # Cache fields pass through as-is so the server can persist them.
    assert turn.usage.get("cache_read_input_tokens") == 50, (
        f"cache_read_input_tokens {turn.usage.get('cache_read_input_tokens')} != 50 — "
        "extra usage keys from ResultMessage.usage should be forwarded verbatim."
    )

    # context_tokens is the real prompt size = input + cache_creation +
    # cache_read (500 + 0 + 50). The runner reads this to track context-window
    # fill; without it the runner falls back to total_tokens (input + output,
    # non-cached only), which under-counts because the bulk of a long
    # conversation's prompt lives in cache_read_input_tokens. Note it differs
    # from total_tokens here (550 != 700) precisely because total ignores the
    # cached prompt while context includes it.
    assert turn.usage["context_tokens"] == 550, (
        f"context_tokens {turn.usage.get('context_tokens')} != 550 (500+0+50) — "
        "context_tokens must sum input + cache_creation + cache_read so the "
        "runner reports accurate, accumulating context-window fill."
    )

    # The resolved model is forwarded in usage so the server cost path can
    # price the turn even when the agent spec pins no llm.model. The key must
    # be present (here it's None — no model is configured in this unit test).
    assert "model" in turn.usage, (
        "TurnComplete.usage is missing the 'model' key — the server cost path "
        "relies on it to price relay turns whose spec pins no llm.model."
    )


@pytest.mark.asyncio
async def test_result_message_is_error_yields_executor_error() -> None:
    """``ResultMessage`` with ``is_error=True`` must surface as ``ExecutorError``.

    When the SDK signals a harness-level failure (e.g. expired login, not logged
    in), ``is_error`` is ``True`` and ``result`` carries the failure text.  The
    executor must route this into an ``ExecutorError`` — not store it as the
    assistant's response.

    Regression guard: before the fix, ``result`` was assigned to ``response_text``
    unconditionally, so the failure appeared as an assistant message with no error
    item and no log line.
    """
    from unittest.mock import patch

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import ExecutorError, TurnComplete

    executor = ClaudeSDKExecutor()
    fake_sdk = _failed_result_sdk("Not logged in · Please run /login")
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert errors, (
        "Expected at least one ExecutorError for is_error=True ResultMessage, got none. "
        "The failure text must not be stored as assistant content."
    )
    assert "Not logged in" in errors[0].message, (
        f"ExecutorError.message {errors[0].message!r} does not contain the failure text."
    )

    # Must not also appear as assistant content
    turns = [e for e in events if isinstance(e, TurnComplete)]
    for t in turns:
        assert "Not logged in" not in (t.response or ""), (
            "Failure text must not appear in TurnComplete.response"
            " — it leaked as assistant content."
        )


@pytest.mark.parametrize(
    "result_text",
    [
        "Failed to authenticate: OAuth session expired and could not be refreshed",
        "Not logged in · Please run /login",
        "Login expired · Please run `/login`",
        "OAuth token revoked · Please run /login",
        "Invalid API key · Please run /login",
        "Authentication failed: invalid or missing API key",
        "Not signed in. Run /login, then retry.",
        "Please run /login to sign in again.",
        "Please run /login to authenticate, or check your authentication settings.",
        "Your account does not have access to Claude. Please login again or contact your "
        "administrator.",
        "Your organization has disabled API key authentication · Run /login to sign in "
        "with your claude.ai account",
        "The claude.ai credential is expired or revoked, and /login requires an interactive "
        "terminal",
    ],
)
def test_claude_auth_failure_text_matches_claude_code_wording(result_text: str) -> None:
    from omnigent.inner.claude_sdk_executor import is_claude_auth_failure_text

    assert is_claude_auth_failure_text(result_text)


@pytest.mark.parametrize(
    "result_text",
    [
        "Prompt is too long",
        "Error: tool execution failed",
        "claude-sdk harness error",
        # A bare /login suggestion is not an authentication failure.
        "Credit balance too low · Run /login to switch accounts",
        "Run /login to enroll it as a trusted device",
        "Please run `/login` to enroll this device",
    ],
)
def test_claude_auth_failure_text_ignores_other_failures(result_text: str) -> None:
    from omnigent.inner.claude_sdk_executor import is_claude_auth_failure_text

    assert not is_claude_auth_failure_text(result_text)


def _failed_result_sdk(result_text: str):
    """Scripted SDK whose only message is a ``ResultMessage`` with ``is_error=True``."""
    from claude_agent_sdk.types import ClaudeAgentOptions as SDKClaudeAgentOptions
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    class _Sentinel:
        pass

    sdk_result = SDKResultMessage(
        subtype="success",
        session_id="s1",
        result=result_text,
        total_cost_usd=0.0,
        duration_ms=100,
        duration_api_ms=80,
        is_error=True,
        num_turns=1,
        usage=None,
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [sdk_result]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    return _FakeSDK


async def _only_executor_error(executor, fake_sdk):
    from unittest.mock import patch

    from omnigent.inner.executor import ExecutorError

    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]
    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert len(errors) == 1, events
    return errors[0]


@pytest.mark.asyncio
async def test_result_message_auth_failure_names_the_fix() -> None:
    """Claude Code's own login failure surfaces with a headline and a next step.

    Without a gateway the harness runs on Claude Code's claude.ai login, so the
    remediation must point at that login rather than at a gateway.
    """
    from omnigent.inner.claude_sdk_executor import (
        CLAUDE_AUTH_FAILED_CODE,
        CLAUDE_AUTH_FAILED_TITLE,
        ClaudeSDKExecutor,
    )

    failure = "Failed to authenticate: OAuth session expired and could not be refreshed"
    error = await _only_executor_error(ClaudeSDKExecutor(), _failed_result_sdk(failure))

    assert error.code == CLAUDE_AUTH_FAILED_CODE
    assert error.title == CLAUDE_AUTH_FAILED_TITLE
    assert error.remediation is not None
    assert "claude auth login" in error.remediation
    assert "setup" in error.remediation
    assert "databrickscfg" not in error.remediation
    # Message-only clients (REPL, SDK stream) still get Claude's text and the next step.
    assert error.message.startswith(failure)
    assert error.remediation in error.message


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("executor_kwargs", "expected", "unexpected"),
    [
        pytest.param(
            {"gateway": True}, "databrickscfg", "claude auth login", id="databricks-profile"
        ),
        pytest.param(
            {
                "gateway": True,
                "gateway_host": "https://gateway.example.com",
                "base_url_override": "https://gateway.example.com/anthropic",
                "gateway_auth_command": "printf token",
            },
            "ANTHROPIC_BASE_URL",
            "databrickscfg",
            id="generic-gateway",
        ),
    ],
)
async def test_result_message_auth_failure_remediation_follows_the_transport(
    executor_kwargs: dict[str, object], expected: str, unexpected: str
) -> None:
    """On a gateway the next step names that gateway's credential, not a claude.ai login."""
    from unittest.mock import patch

    from omnigent.inner.claude_sdk_executor import CLAUDE_AUTH_FAILED_CODE, ClaudeSDKExecutor

    with patch(
        "omnigent.inner.claude_sdk_executor._resolve_gateway_env",
        return_value={
            "ANTHROPIC_BASE_URL": "https://host/ai-gateway/anthropic",
            "CLAUDE_CODE_API_KEY_HELPER_TTL_MS": "900000",
            "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
            "OMNIGENT_CLAUDE_API_KEY_HELPER": "databricks auth token ...",
        },
    ):
        executor = ClaudeSDKExecutor(**executor_kwargs)
    error = await _only_executor_error(
        executor, _failed_result_sdk("Failed to authenticate: invalid or missing API key")
    )

    assert error.code == CLAUDE_AUTH_FAILED_CODE
    assert error.remediation is not None
    assert expected in error.remediation
    assert unexpected not in error.remediation
    assert error.remediation in error.message


@pytest.mark.asyncio
async def test_endpoint_not_found_retry_stays_unclassified() -> None:
    """A 404 api_retry ends the turn with the endpoint hint and no authentication code."""
    from claude_agent_sdk.types import ClaudeAgentOptions as SDKClaudeAgentOptions
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent
    from claude_agent_sdk.types import SystemMessage as SDKSystemMessage

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _Sentinel:
        pass

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        ResultMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = SDKSystemMessage
        StreamEvent = SDKStreamEvent
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [
            SDKSystemMessage(
                subtype="api_retry",
                data={
                    "type": "system",
                    "subtype": "api_retry",
                    "attempt": 1,
                    "max_retries": 10,
                    "retry_delay_ms": 500,
                    "error_status": 404,
                    "error": "not_found_error",
                },
            )
        ]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    error = await _only_executor_error(ClaudeSDKExecutor(), _FakeSDK)

    assert "endpoint was not found" in error.message
    assert "ANTHROPIC_BASE_URL" in error.message
    assert error.code is None
    assert error.remediation is None


@pytest.mark.asyncio
async def test_result_message_other_failure_stays_unclassified() -> None:
    """A failed result that is not about authentication keeps the generic error path."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    error = await _only_executor_error(
        ClaudeSDKExecutor(), _failed_result_sdk("Prompt is too long")
    )

    assert error.message == "Prompt is too long"
    assert error.code is None
    assert error.title is None
    assert error.remediation is None


@pytest.mark.asyncio
async def test_context_tokens_uses_last_call_not_cumulative_on_multi_iteration_turn() -> None:
    """``context_tokens`` must reflect the LAST API call, not the cumulative sum.

    A single user turn can drive several internal API calls (the SDK's
    tool-use loop). ``ResultMessage.usage`` reports the CUMULATIVE usage
    across all of them, so its ``input_tokens`` / cache buckets are the
    sum of every iteration's prompt. Since each iteration re-sends the
    whole (growing) conversation, summing the prompt side K-fold
    over-counts context — which surfaced as the toolbar context ring
    spiking up during a tool-using turn and snapping back down on the
    next plain turn.

    Context-window FILL is a single prompt's size, not a billing sum: the
    final call's prompt already contains the full conversation that carries
    into the next turn. The executor captures each ``message_start``'s
    per-call usage and uses the LAST one for ``context_tokens`` (mirroring
    the openai-agents executor's ``raw_responses[-1]`` choice), while still
    reporting the cumulative totals for billing.

    Regression guard: before this fix ``context_tokens`` was
    ``cumulative_input + cumulative_cache_read`` (= 21100 here), which is
    the K-fold over-count. The correct value is the last call's prompt
    (= 10800).
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _Sentinel:
        pass

    def _message_start(usage: dict[str, int]) -> SDKStreamEvent:
        # One ``message_start`` opens one API call and carries that call's
        # prompt-side usage. Two of them model a two-call (one tool-loop)
        # turn; the executor must keep only the last for context.
        return SDKStreamEvent(
            uuid="u",
            session_id="s1",
            event={"type": "message_start", "message": {"usage": usage}},
        )

    # Call 1 (cold-ish): non-cached input 300 + 10000 read from cache.
    first_call = _message_start(
        {"input_tokens": 300, "cache_read_input_tokens": 10000, "cache_creation_input_tokens": 0}
    )
    # Call 2 (final, after the tool result is appended): the conversation
    # grew, so this prompt is the real context = 500 + 10300 = 10800.
    second_call = _message_start(
        {"input_tokens": 500, "cache_read_input_tokens": 10300, "cache_creation_input_tokens": 0}
    )
    # ResultMessage carries the CUMULATIVE sum across both calls:
    # input 800, cache_read 20300, output 250.
    cumulative_result = SDKResultMessage(
        subtype="result",
        session_id="s1",
        result="done",
        total_cost_usd=0.0,
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=2,
        usage={
            "input_tokens": 800,
            "output_tokens": 250,
            "cache_read_input_tokens": 20300,
            "cache_creation_input_tokens": 0,
        },
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [first_call, second_call, cumulative_result]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor()
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    turn = next(e for e in events if isinstance(e, TurnComplete))
    assert turn.usage is not None, "TurnComplete.usage is None on a multi-call turn."

    # context_tokens = LAST call's prompt (500 + 0 + 10300), NOT the
    # cumulative sum (800 + 20300 = 21100). This is the whole point of the
    # fix: a tool-using turn must not inflate the context ring.
    assert turn.usage["context_tokens"] == 10800, (
        f"context_tokens {turn.usage.get('context_tokens')} != 10800 — must be the "
        "LAST message_start call's prompt (input+cache_creation+cache_read), not the "
        "cumulative ResultMessage sum (21100). Using the cumulative value over-counts "
        "context K-fold on a K-call turn."
    )
    assert turn.usage["context_tokens"] != 21100, (
        "context_tokens equals the cumulative over-count (21100) — the executor is "
        "summing prompt usage across tool-loop iterations instead of taking the last call."
    )

    # Billing totals still come from the cumulative ResultMessage.usage so
    # cost is charged for every call, not just the last one.
    assert turn.usage["input_tokens"] == 800, (
        f"input_tokens {turn.usage.get('input_tokens')} != 800 — billing input must "
        "stay the cumulative cross-call sum from ResultMessage.usage."
    )
    assert turn.usage["output_tokens"] == 250, (
        f"output_tokens {turn.usage.get('output_tokens')} != 250 — billing output must "
        "stay the cumulative sum from ResultMessage.usage."
    )
    assert turn.usage["total_tokens"] == 1050, (
        f"total_tokens {turn.usage.get('total_tokens')} != 1050 (800+250) — total must "
        "be the cumulative input + output for billing."
    )


@pytest.mark.asyncio
async def test_context_tokens_emitted_when_turn_ends_without_result_message() -> None:
    """A turn that never reaches ``ResultMessage`` still reports ``context_tokens``.

    ``context_tokens`` (context-window fill) is normally assembled in the
    ``ResultMessage`` branch at successful completion. But a turn can end the
    stream without a ``ResultMessage`` — the CLI can close the stream early,
    or the turn can be cut short before its final usage is reported. Before
    this fix the executor yielded ``TurnComplete(usage=None)`` in that case,
    so the occupancy meter froze at the previous successful turn's value and
    showed a misleadingly low fill exactly when a session was in trouble
    (#1533).

    The per-call prompt size is already observed mid-turn from each
    ``message_start`` event, so when no ``ResultMessage`` arrives the executor
    must fall back to that observed usage and still emit ``context_tokens``.

    Regression guard: pre-fix ``turn.usage`` is ``None`` here because the
    stream carries only a ``message_start`` and then stops.
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _Sentinel:
        pass

    # The turn opens one API call (carrying its prompt usage) and then the
    # stream simply ends — no ResultMessage, mirroring an early CLI stream
    # close or a turn cut short before final usage is reported.
    message_start = SDKStreamEvent(
        uuid="u1",
        session_id="s1",
        event={
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 400,
                    "cache_read_input_tokens": 9000,
                    "cache_creation_input_tokens": 100,
                }
            },
        },
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [message_start]  # note: no ResultMessage

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor()
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    turn = next(e for e in events if isinstance(e, TurnComplete))
    assert turn.usage is not None, (
        "TurnComplete.usage is None on a turn that ended without a ResultMessage — "
        "the observed message_start prompt usage was discarded, so the occupancy "
        "meter freezes at the last successful turn's value (#1533)."
    )

    # context_tokens = the observed prompt = input + cache_creation + cache_read
    # (400 + 100 + 9000), so a failed/early-ending turn still refreshes fill.
    assert turn.usage["context_tokens"] == 9500, (
        f"context_tokens {turn.usage.get('context_tokens')} != 9500 (400+100+9000) — "
        "an incomplete turn must report context_tokens from the last observed "
        "message_start prompt so the occupancy meter does not freeze."
    )
    # output_tokens is unknown on an incomplete turn, so it is reported as 0
    # rather than guessed; the meaningful field here is context_tokens.
    assert turn.usage["output_tokens"] == 0, (
        f"output_tokens {turn.usage.get('output_tokens')} != 0 — output is unknown "
        "on an incomplete turn and must not be fabricated."
    )
    assert "model" in turn.usage, (
        "TurnComplete.usage is missing the 'model' key on the incomplete-turn path."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("synthetic_error", [False, True])
@pytest.mark.parametrize("observed", [True, False])
async def test_assistant_message_model_flows_to_turn_usage(
    synthetic_error: bool,
    observed: bool,
) -> None:
    """The SDK's assistant-message model is forwarded in ``TurnComplete.usage``.

    When the agent spec pins no model (a delegating supervisor on the gateway),
    the resolved config model is ``None`` — but the Claude SDK reports the
    concrete model on each ``AssistantMessage``. The executor captures it and
    forwards it as ``usage["model"]`` so the server cost path can price the
    turn. A regression here leaves cost unpriced ("—") for every unpinned
    claude-sdk agent (the debbie/debby supervisors).
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _AsstMsg:
        """Minimal stand-in for the SDK AssistantMessage (carries model)."""

        def __init__(self, content: list[object], model: str) -> None:
            self.content = content
            self.model = model

    assistant = _AsstMsg(content=[], model="claude-opus-4-8")
    sdk_result = SDKResultMessage(
        subtype="result",
        session_id="s1",
        result="hi",
        total_cost_usd=0.0,
        duration_ms=1,
        duration_api_ms=1,
        is_error=synthetic_error,
        num_turns=1,
        usage={"input_tokens": 100, "output_tokens": 50},
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _AsstMsg
        UserMessage = type("_U", (), {})
        SystemMessage = type("_S", (), {})
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [assistant] if observed else []
        if synthetic_error:
            messages.append(_AsstMsg(content=[], model="<synthetic>"))
        messages.append(sdk_result)

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):  # type: ignore[no-untyped-def]
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor(model=None if observed else "configured-model")
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    terminal_type = ExecutorError if synthetic_error else TurnComplete
    turn = next(e for e in events if isinstance(e, terminal_type))
    assert turn.usage is not None
    # Synthetic errors preserve the last real report, or the configured fallback.
    expected_model = "claude-opus-4-8" if observed else "configured-model"
    assert turn.usage["model"] == expected_model


@pytest.mark.asyncio
async def test_result_message_usage_none_yields_turn_complete_without_usage() -> None:
    """When ``ResultMessage.usage`` is ``None``, ``TurnComplete.usage`` is ``None``.

    The executor must not synthesize fake usage when the SDK doesn't report it
    (e.g. Databricks gateway not returning usage). ``None`` usage causes the
    REPL to fall back to its local ``count_tokens()`` estimate, which is correct
    behaviour — no invented numbers should appear in the context ring.

    Regression guard: if the usage-capture code unconditionally sets
    ``turn_usage = {}`` (or any non-None dict), the REPL would display
    ``0 / 200k (0%)`` instead of triggering the local estimate.
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    class _Sentinel:
        pass

    sdk_result = SDKResultMessage(
        subtype="result",
        session_id="s1",
        result="Hello",
        total_cost_usd=0.0,
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        usage=None,  # SDK didn't report usage
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [sdk_result]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor()
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    turn = next(e for e in events if isinstance(e, TurnComplete))

    # usage=None triggers the REPL's local count_tokens() fallback,
    # which is the right behaviour when the SDK doesn't report usage.
    # A non-None empty dict {} would short-circuit the fallback with 0 tokens.
    assert turn.usage is None, (
        f"TurnComplete.usage should be None when ResultMessage.usage is None, "
        f"got {turn.usage!r}. An empty dict would display 0 tokens in the ring."
    )


# ---------------------------------------------------------------------------
# Tests: pre-execution TOOL_CALL policy gate (can_use_tool)
# ---------------------------------------------------------------------------


class TestToolCallPolicyGate(unittest.TestCase):
    """The ``can_use_tool`` gate that enforces TOOL_CALL policy on
    connector-native MCP tools (``mcp__github__*`` etc.) before they run.
    """

    def _make_executor(self, permission_mode="bypassPermissions"):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        return ClaudeSDKExecutor(permission_mode=permission_mode)

    @staticmethod
    def _verdict(action, reason=None):
        from omnigent.runtime.harnesses._scaffold import PolicyVerdictPayload

        return PolicyVerdictPayload(action=action, reason=reason)

    @staticmethod
    def _perm_ctx():
        return SimpleNamespace(tool_use_id="tu_1", agent_id=None, suggestions=[])

    def test_connector_native_tool_triggers_tool_call_eval(self):
        """A connector-native tool name drives a PHASE_TOOL_CALL evaluation
        with the SDK-native tool name and arguments."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor()
            evaluator = AsyncMock(return_value=self._verdict("POLICY_ACTION_ALLOW"))
            executor._policy_evaluator = evaluator

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug", "body": "x"},
                self._perm_ctx(),
            )

            evaluator.assert_awaited_once()
            phase, data = evaluator.await_args.args
            self.assertEqual(phase, "PHASE_TOOL_CALL")
            self.assertEqual(
                data,
                {
                    "name": "mcp__github__issue_write",
                    "arguments": {"title": "bug", "body": "x"},
                },
            )
            self.assertIsInstance(result, PermissionResultAllow)

        _run(_t())

    def test_deny_verdict_blocks_execution(self):
        """A DENY verdict returns PermissionResultDeny carrying the
        policy's reason and never reaches the elicitation handler."""
        from claude_agent_sdk import PermissionResultDeny

        async def _t():
            executor = self._make_executor(permission_mode="default")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_DENY", reason="no writes to github")
            )
            elicit = AsyncMock(return_value=True)
            executor._elicitation_handler = elicit

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultDeny)
            self.assertEqual(result.message, "no writes to github")
            # DENY short-circuits — no human prompt.
            elicit.assert_not_awaited()

        _run(_t())

    def test_ask_verdict_prompts_even_under_bypass(self):
        """A raw ASK verdict is supported by routing to Omnigent
        elicitation, even under bypassPermissions."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ASK", reason="approval required")
            )
            elicit = AsyncMock(return_value=True)
            executor._elicitation_handler = elicit

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultAllow)
            elicit.assert_awaited_once_with("mcp__github__issue_write", {"title": "bug"})

        _run(_t())

    def test_ask_verdict_denies_when_user_declines(self):
        """A declined raw ASK blocks execution with the policy reason."""
        from claude_agent_sdk import PermissionResultDeny

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ASK", reason="approval required")
            )
            executor._elicitation_handler = AsyncMock(return_value=False)

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultDeny)
            self.assertEqual(result.message, "approval required")

        _run(_t())

    def test_ask_verdict_without_elicitation_handler_fails_closed(self):
        """If raw ASK reaches the callback but no handler is available,
        the tool must not run."""
        from claude_agent_sdk import PermissionResultDeny

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ASK", reason="approval required")
            )

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultDeny)
            self.assertEqual(result.message, "approval required")

        _run(_t())

    def test_unspecified_verdict_falls_through(self):
        """UNSPECIFIED is a proto no-op verdict and should behave like no match."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_UNSPECIFIED")
            )

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_read",
                {"number": 1},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultAllow)

        _run(_t())

    def test_unexpected_verdict_fails_closed(self):
        """Unknown policy actions should not silently allow a tool call."""
        from claude_agent_sdk import PermissionResultDeny

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(return_value=self._verdict("BOGUS"))

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_write",
                {"title": "bug"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultDeny)
            self.assertIn("Unexpected Coral TOOL_CALL policy verdict", result.message)

        _run(_t())

    def test_allow_verdict_no_human_prompt_under_bypass(self):
        """ALLOW under bypassPermissions allows the call with no human
        prompt, preserving bypass ergonomics."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ALLOW")
            )
            elicit = AsyncMock(return_value=True)
            executor._elicitation_handler = elicit

            result = await executor._can_use_tool_gate(
                "mcp__github__issue_read",
                {"number": 1},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultAllow)
            elicit.assert_not_awaited()

        _run(_t())

    def test_no_policy_evaluator_no_match_allows_silently(self):
        """With no policy evaluator wired (default ALLOW), the gate allows
        with no evaluation and no human prompt under bypassPermissions."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            # No _policy_evaluator set, no elicitation handler.
            result = await executor._can_use_tool_gate(
                "mcp__atlassian__createJiraIssue",
                {"summary": "x"},
                self._perm_ctx(),
            )
            self.assertIsInstance(result, PermissionResultAllow)

        _run(_t())

    def test_omnigent_own_tool_skips_evaluation(self):
        """``mcp__omnigent__*`` tools are already TOOL_CALL-gated server-side
        via the dispatch bridge / ProxyMcpManager, so the gate must NOT
        evaluate them again (avoids double-evaluation)."""
        from claude_agent_sdk import PermissionResultAllow

        async def _t():
            executor = self._make_executor(permission_mode="bypassPermissions")
            evaluator = AsyncMock(return_value=self._verdict("POLICY_ACTION_ALLOW"))
            executor._policy_evaluator = evaluator

            result = await executor._can_use_tool_gate(
                "mcp__omnigent__sys_os_read",
                {"path": "/tmp/x"},
                self._perm_ctx(),
            )

            self.assertIsInstance(result, PermissionResultAllow)
            evaluator.assert_not_awaited()

        _run(_t())

    def test_non_bypass_runs_elicitation_after_policy_allow(self):
        """In a non-bypass mode, a policy ALLOW falls through to the
        human-consent elicitation gate (pre-existing behavior)."""
        from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny

        async def _t():
            executor = self._make_executor(permission_mode="default")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ALLOW")
            )

            # Human approves.
            executor._elicitation_handler = AsyncMock(return_value=True)
            approved = await executor._can_use_tool_gate(
                "mcp__github__issue_read", {}, self._perm_ctx()
            )
            self.assertIsInstance(approved, PermissionResultAllow)

            # Human denies.
            executor._elicitation_handler = AsyncMock(return_value=False)
            denied = await executor._can_use_tool_gate(
                "mcp__github__issue_read", {}, self._perm_ctx()
            )
            self.assertIsInstance(denied, PermissionResultDeny)

        _run(_t())

    def test_gate_installed_under_bypass_permissions(self):
        """run_turn installs the can_use_tool gate even under
        bypassPermissions when a policy evaluator is wired — the
        regression this feature fixes."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor(permission_mode="bypassPermissions")
            executor._policy_evaluator = AsyncMock(
                return_value=self._verdict("POLICY_ACTION_ALLOW")
            )

            captured = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["can_use_tool"] = options.can_use_tool
                raise RuntimeError("stop after options build")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            # Bound-method identity differs per access; compare equality.
            self.assertEqual(captured["can_use_tool"], executor._can_use_tool_gate)
            self.assertIsNotNone(captured["can_use_tool"])

        _run(_t())

    def test_gate_not_installed_without_evaluator_or_handler(self):
        """With neither a policy evaluator nor an elicitation handler, no
        can_use_tool callback is installed (unchanged baseline)."""
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        async def _t():
            executor = ClaudeSDKExecutor(permission_mode="bypassPermissions")
            captured = {}

            async def fake_get_or_create_client(sdk, *, session_key, options, model):
                captured["can_use_tool"] = options.can_use_tool
                raise RuntimeError("stop after options build")

            with patch.object(
                executor,
                "_get_or_create_client",
                side_effect=fake_get_or_create_client,
            ):
                with self.assertRaises(RuntimeError):
                    async for _ in executor.run_turn([{"role": "user", "content": "hi"}], [], ""):
                        pass

            self.assertIsNone(captured["can_use_tool"])

        _run(_t())


# ---------------------------------------------------------------------------
# Tests: Compaction detection via PreCompact hook
# ---------------------------------------------------------------------------


def test_precompact_hook_emits_compaction_complete_with_session_messages() -> None:
    """When PreCompact fires and a ResultMessage carries a session_id,
    CompactionComplete is emitted with compacted_messages read from
    the CLI's session transcript."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete

    class _ResultMessage:
        def __init__(self, session_id, result):
            self.session_id = session_id
            self.result = result
            self.content = []
            self.model = "claude-test"
            self.usage = type(
                "U",
                (),
                {
                    "input_tokens": 500,
                    "output_tokens": 100,
                },
            )()

    class _SystemMessage:
        def __init__(self, subtype, data, hook_event_name=None):
            self.subtype = subtype
            self.data = data
            self.hook_event_name = hook_event_name

    class _HookEventMessage(_SystemMessage):
        pass

    class _FakeSessionMessage:
        def __init__(self, type, message):
            self.type = type
            self.message = message

    class _FakeSDK(_sdk_types()):
        SystemMessage = _SystemMessage
        ResultMessage = _ResultMessage
        messages: list = []

        class ClaudeSDKClient(_SDKClient):
            async def query(self, prompt, session_id="default"):
                _FakeSDK.messages = [
                    _HookEventMessage(
                        subtype="hook_started",
                        data={"hook_event": "PreCompact"},
                        hook_event_name="PreCompact",
                    ),
                    _ResultMessage("claude-uuid-123", "compacted result"),
                ]

            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    fake_session_msgs = [
        _FakeSessionMessage("user", {"content": [{"type": "text", "text": "hi"}]}),
        _FakeSessionMessage("assistant", {"content": [{"type": "text", "text": "compacted"}]}),
    ]

    async def _t():
        executor = ClaudeSDKExecutor()
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            patch(
                "claude_agent_sdk.get_session_messages",
                return_value=fake_session_msgs,
            ) as mock_get_msgs,
        ):
            events = [
                e
                async for e in executor.run_turn(
                    [{"role": "user", "content": "hi", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        compaction_events = [e for e in events if isinstance(e, CompactionComplete)]
        assert len(compaction_events) == 1
        ce = compaction_events[0]
        assert ce.compacted_messages is not None
        assert len(ce.compacted_messages) == 2
        assert ce.compacted_messages[0]["role"] == "user"
        assert ce.compacted_messages[1]["role"] == "assistant"
        mock_get_msgs.assert_called_once_with("claude-uuid-123", directory=None)
        # CompactionStarted before CompactionComplete before TurnComplete
        from omnigent.inner.executor import CompactionStarted

        started_events = [e for e in events if isinstance(e, CompactionStarted)]
        assert len(started_events) == 1
        turn_completes = [e for e in events if isinstance(e, TurnComplete)]
        assert len(turn_completes) == 1
        assert events.index(started_events[0]) < events.index(compaction_events[0])
        assert events.index(compaction_events[0]) < events.index(turn_completes[0])

    _run(_t())


def test_precompact_exception_persists_compaction_before_executor_error(tmp_path: Path) -> None:
    """A stream failure after PreCompact still emits the durable boundary."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete, CompactionStarted

    class _SystemMessage:
        def __init__(self, subtype, data, hook_event_name=None, session_id=None):
            self.subtype = subtype
            self.data = data
            self.hook_event_name = hook_event_name
            self.session_id = session_id

    class _FakeSessionMessage:
        def __init__(self, type, message):
            self.type = type
            self.message = message

    class _FakeSDK(_sdk_types()):
        SystemMessage = _SystemMessage

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                yield _SystemMessage(
                    subtype="hook_started",
                    data={
                        "hook_event": "PreCompact",
                        "session_id": "claude-uuid-error",
                        "transcript_path": str(transcript_path),
                    },
                    hook_event_name="PreCompact",
                    session_id="claude-uuid-error",
                )
                with transcript_path.open("a", encoding="utf-8") as transcript:
                    transcript.write(
                        json.dumps(
                            {
                                "type": "user",
                                "uuid": "compact-summary-1",
                                "isCompactSummary": True,
                                "message": {
                                    "role": "user",
                                    "content": "compacted summary",
                                },
                            }
                        )
                        + "\n"
                    )
                raise RuntimeError("Autocompact is thrashing: the context refilled to the limit")

    fake_session_msgs = [
        _FakeSessionMessage(
            "assistant",
            {"content": [{"type": "text", "text": "compacted summary"}]},
        )
    ]
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": "precompact-1",
                "message": {"role": "user", "content": "continue"},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    async def _t():
        executor = ClaudeSDKExecutor()
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            patch(
                "claude_agent_sdk.get_session_messages",
                return_value=fake_session_msgs,
            ) as mock_get_msgs,
        ):
            events = [
                event
                async for event in executor.run_turn(
                    [{"role": "user", "content": "continue", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        started = [event for event in events if isinstance(event, CompactionStarted)]
        completed = [event for event in events if isinstance(event, CompactionComplete)]
        errors = [event for event in events if isinstance(event, ExecutorError)]

        assert len(started) == 1
        assert len(completed) == 1
        assert len(errors) == 1
        assert not [event for event in events if isinstance(event, TurnComplete)]
        assert events.index(started[0]) < events.index(completed[0])
        assert events.index(completed[0]) < events.index(errors[0])
        assert completed[0].compacted_messages == [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "text", "text": "compacted summary"}],
            }
        ]
        mock_get_msgs.assert_called_once_with("claude-uuid-error", directory=None)

    _run(_t())


@pytest.mark.parametrize(
    ("transcript_location", "expect_checkpoint"),
    [("top_level", True), ("nested", False)],
)
def test_precompact_exception_sdk_wire_payload_contract(
    tmp_path: Path,
    transcript_location: str,
    expect_checkpoint: bool,
) -> None:
    """The SDK-decoded hook payload exposes a safe transcript boundary."""
    import claude_agent_sdk as real_sdk
    from claude_agent_sdk._internal.message_parser import parse_message

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete

    class _FakeSessionMessage:
        def __init__(self, type, message):
            self.type = type
            self.message = message

    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text(
        json.dumps(
            {
                "type": "user",
                "uuid": "precompact-wire-1",
                "message": {"role": "user", "content": "continue"},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    raw_hook_payload = {
        "type": "system",
        "subtype": "hook_started",
        "hook_id": "hook-precompact-wire-1",
        "hook_name": "PreCompact:auto",
        "hook_event": "PreCompact",
        "uuid": "hook-event-precompact-wire-1",
        "session_id": "claude-uuid-wire",
        "cwd": str(tmp_path),
        "trigger": "auto",
        "custom_instructions": None,
    }
    if transcript_location == "top_level":
        raw_hook_payload["transcript_path"] = str(transcript_path)
    else:
        raw_hook_payload["input"] = {"transcript_path": str(transcript_path)}

    hook_message = parse_message(raw_hook_payload)
    assert isinstance(hook_message, real_sdk.HookEventMessage)

    class _FakeSDK(_sdk_types()):
        AssistantMessage = real_sdk.AssistantMessage
        UserMessage = real_sdk.UserMessage
        SystemMessage = real_sdk.SystemMessage
        ResultMessage = real_sdk.ResultMessage
        StreamEvent = real_sdk.StreamEvent

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                yield hook_message
                with transcript_path.open("a", encoding="utf-8") as transcript:
                    transcript.write(
                        json.dumps(
                            {
                                "type": "user",
                                "uuid": "compact-summary-wire-1",
                                "isCompactSummary": True,
                                "message": {
                                    "role": "user",
                                    "content": "compacted summary",
                                },
                            }
                        )
                        + "\n"
                    )
                raise RuntimeError("Autocompact refilled the context")

    fake_session_msgs = [
        _FakeSessionMessage(
            "assistant",
            {"content": [{"type": "text", "text": "compacted summary"}]},
        )
    ]

    async def _t():
        executor = ClaudeSDKExecutor()
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            patch(
                "claude_agent_sdk.get_session_messages",
                return_value=fake_session_msgs,
            ) as mock_get_messages,
        ):
            events = [
                event
                async for event in executor.run_turn(
                    [{"role": "user", "content": "continue", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        checkpoints = [event for event in events if isinstance(event, CompactionComplete)]
        assert len(checkpoints) == int(expect_checkpoint)
        if expect_checkpoint:
            mock_get_messages.assert_called_once_with("claude-uuid-wire", directory=None)
        else:
            mock_get_messages.assert_not_called()

    _run(_t())


@pytest.mark.parametrize("session_read", [[], RuntimeError("transcript not flushed")])
def test_precompact_exception_preserves_history_without_exportable_checkpoint(
    tmp_path: Path,
    session_read: list[object] | Exception,
) -> None:
    """An empty or failed export never replaces full history with a placeholder."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete

    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text("", encoding="utf-8")

    class _SystemMessage:
        def __init__(self, subtype, data, hook_event_name=None, session_id=None):
            self.subtype = subtype
            self.data = data
            self.hook_event_name = hook_event_name
            self.session_id = session_id

    class _FakeSDK(_sdk_types()):
        SystemMessage = _SystemMessage

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                yield _SystemMessage(
                    subtype="hook_started",
                    data={
                        "hook_event": "PreCompact",
                        "session_id": "claude-uuid-error",
                        "transcript_path": str(transcript_path),
                    },
                    hook_event_name="PreCompact",
                    session_id="claude-uuid-error",
                )
                with transcript_path.open("a", encoding="utf-8") as transcript:
                    transcript.write(
                        json.dumps(
                            {
                                "type": "user",
                                "uuid": "compact-summary-1",
                                "isCompactSummary": True,
                                "message": {
                                    "role": "user",
                                    "content": "compacted summary",
                                },
                            }
                        )
                        + "\n"
                    )
                raise RuntimeError("Autocompact is thrashing: the context refilled to the limit")

    async def _t():
        executor = ClaudeSDKExecutor()
        get_messages = (
            patch("claude_agent_sdk.get_session_messages", side_effect=session_read)
            if isinstance(session_read, Exception)
            else patch("claude_agent_sdk.get_session_messages", return_value=session_read)
        )
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            get_messages,
        ):
            events = [
                event
                async for event in executor.run_turn(
                    [{"role": "user", "content": "continue", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        assert not [event for event in events if isinstance(event, CompactionComplete)]
        assert len([event for event in events if isinstance(event, ExecutorError)]) == 1

    _run(_t())


def test_precompact_exception_without_new_summary_preserves_history(tmp_path: Path) -> None:
    """PreCompact alone is not evidence that Claude finished compaction."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete

    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text("", encoding="utf-8")

    class _SystemMessage:
        def __init__(self, subtype, data, hook_event_name=None, session_id=None):
            self.subtype = subtype
            self.data = data
            self.hook_event_name = hook_event_name
            self.session_id = session_id

    class _FakeSDK(_sdk_types()):
        SystemMessage = _SystemMessage

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                yield _SystemMessage(
                    subtype="hook_started",
                    data={
                        "hook_event": "PreCompact",
                        "session_id": "claude-uuid-error",
                        "transcript_path": str(transcript_path),
                    },
                    hook_event_name="PreCompact",
                    session_id="claude-uuid-error",
                )
                raise RuntimeError("stream failed before compaction completed")

    async def _t():
        executor = ClaudeSDKExecutor()
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            patch("claude_agent_sdk.get_session_messages") as mock_get_messages,
        ):
            events = [
                event
                async for event in executor.run_turn(
                    [{"role": "user", "content": "continue", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        assert not [event for event in events if isinstance(event, CompactionComplete)]
        assert len([event for event in events if isinstance(event, ExecutorError)]) == 1
        mock_get_messages.assert_not_called()

    _run(_t())


def test_precompact_hook_emits_compaction_started_before_complete() -> None:
    """CompactionStarted is yielded when PreCompact fires, before CompactionComplete.

    This ensures clients see the in-progress signal while compaction is
    still happening, rather than both events arriving back-to-back after
    the turn ends.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete, CompactionStarted

    class _ResultMessage:
        def __init__(self, session_id, result):
            self.session_id = session_id
            self.result = result
            self.content = []
            self.model = "claude-test"
            self.usage = type(
                "U",
                (),
                {"input_tokens": 500, "output_tokens": 100},
            )()

    class _SystemMessage:
        def __init__(self, subtype, data, hook_event_name=None):
            self.subtype = subtype
            self.data = data
            self.hook_event_name = hook_event_name

    class _FakeSessionMessage:
        def __init__(self, type, message):
            self.type = type
            self.message = message

    class _FakeSDK(_sdk_types()):
        SystemMessage = _SystemMessage
        ResultMessage = _ResultMessage
        messages: list = []

        class ClaudeSDKClient(_SDKClient):
            async def query(self, prompt, session_id="default"):
                _FakeSDK.messages = [
                    _SystemMessage(
                        subtype="hook_started",
                        data={"hook_event": "PreCompact"},
                        hook_event_name="PreCompact",
                    ),
                    _ResultMessage("claude-uuid-456", "compacted result"),
                ]

            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    async def _t():
        executor = ClaudeSDKExecutor()
        with (
            patch(
                "omnigent.inner.claude_sdk_executor._ensure_sdk",
                return_value=_FakeSDK,
            ),
            patch(
                "claude_agent_sdk.get_session_messages",
                return_value=[
                    _FakeSessionMessage(
                        "user",
                        {"content": [{"type": "text", "text": "compacted summary"}]},
                    )
                ],
            ),
        ):
            events = [
                e
                async for e in executor.run_turn(
                    [{"role": "user", "content": "hi", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        started = [e for e in events if isinstance(e, CompactionStarted)]
        completed = [e for e in events if isinstance(e, CompactionComplete)]
        assert len(started) == 1, "expected exactly one CompactionStarted"
        assert len(completed) == 1, "expected exactly one CompactionComplete"
        assert events.index(started[0]) < events.index(completed[0]), (
            "CompactionStarted must precede CompactionComplete"
        )

    _run(_t())


def test_no_precompact_no_compaction_event() -> None:
    """When no PreCompact hook fires, no CompactionComplete is yielded."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import CompactionComplete

    class _ResultMessage:
        def __init__(self, session_id, result):
            self.session_id = session_id
            self.result = result
            self.content = []
            self.model = "claude-test"
            self.usage = type(
                "U",
                (),
                {
                    "input_tokens": 500,
                    "output_tokens": 100,
                },
            )()

    class _FakeSDK(_sdk_types()):
        ResultMessage = _ResultMessage
        messages: list = []

        class ClaudeSDKClient(_SDKClient):
            async def query(self, prompt, session_id="default"):
                _FakeSDK.messages = [_ResultMessage(session_id, "normal result")]

            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    async def _t():
        executor = ClaudeSDKExecutor()
        with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
            events = [
                e
                async for e in executor.run_turn(
                    [{"role": "user", "content": "hi", "session_id": "s1"}],
                    [],
                    "",
                )
            ]

        compaction_events = [e for e in events if isinstance(e, CompactionComplete)]
        assert len(compaction_events) == 0

    _run(_t())


def test_find_system_claude_delegates_to_shared_resolver(monkeypatch) -> None:
    """``_find_system_claude`` resolves claude via the shared resolver with the
    OMNIGENT_CLAUDE_PATH override, so an nvm/npm-installed claude off the host
    daemon's frozen PATH is still found. (The resolver's PATH/override/fallback
    behavior is covered in tests/inner/test_proc_and_platform.py.)"""
    from omnigent.inner import claude_sdk_executor as cse

    captured = {}

    def fake_resolve(name, *, env_var=None):
        captured["name"] = name
        captured["env_var"] = env_var
        return "/opt/homebrew/bin/claude"

    monkeypatch.setattr(cse, "resolve_cli_binary", fake_resolve)
    assert cse._find_system_claude() == "/opt/homebrew/bin/claude"
    assert captured == {"name": "claude", "env_var": "OMNIGENT_CLAUDE_PATH"}


def test_claude_sdk_does_not_claim_live_message_queue() -> None:
    """ClaudeSDKExecutor must not advertise live message queue support.

    query() queues a new turn on stdin rather than injecting into the active
    turn, so returning True from enqueue_session_message caused a permanent
    one-turn-behind desync (issue #3472). The executor must return False from
    both methods so the adapter keeps the message buffered and delivers it as
    a continuation turn after the active turn ends.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    executor = ClaudeSDKExecutor()
    assert executor.supports_live_message_queue() is False


@pytest.mark.asyncio
async def test_enqueue_session_message_returns_false_without_queuing() -> None:
    """enqueue_session_message must return False and never call query().

    Calling query() while a turn is active queues a new turn, not an
    in-turn injection, which produces the desync from issue #3472.
    """
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    executor = ClaudeSDKExecutor()
    query_called = False

    class _FakeClient:
        async def query(self, *args, **kwargs):
            nonlocal query_called
            query_called = True

    # Inject a fake client state so the session key is known.
    executor._clients["s1"] = SimpleNamespace(client=_FakeClient())

    result = await executor.enqueue_session_message("s1", "hello")

    assert result is False
    assert not query_called, "query() must not be called during enqueue"


@pytest.mark.asyncio
async def test_terminal_error_carries_observed_usage() -> None:
    """A terminal-error turn still reports the usage it observed mid-turn.

    A turn can fail AFTER the model call started — the stream dies and the
    CLI's retries are rejected (auth failure), or the ``ResultMessage``
    arrives with ``is_error=True``. The prompt size was already observed
    from ``message_start``, and discarding it froze the context-occupancy
    meter at the previous successful turn's value exactly when the session
    was in trouble.

    Regression guard: pre-fix the ``terminal_error`` path yielded
    ``ExecutorError`` with no usage, so nothing downstream could update
    the meter on a failed turn.
    """
    from unittest.mock import patch

    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import ExecutorError

    class _Sentinel:
        pass

    # The model call opens (message_start carries the prompt usage), then the
    # harness reports a terminal failure via ResultMessage(is_error=True).
    message_start = SDKStreamEvent(
        uuid="u1",
        session_id="s1",
        event={
            "type": "message_start",
            "message": {
                "usage": {
                    "input_tokens": 400,
                    "cache_read_input_tokens": 99_000,
                    "cache_creation_input_tokens": 600,
                }
            },
        },
    )
    sdk_result = SDKResultMessage(
        subtype="success",
        session_id="s1",
        result="authentication failed",
        total_cost_usd=0.0,
        duration_ms=10,
        duration_api_ms=8,
        is_error=True,
        num_turns=1,
        usage=None,
    )

    class _FakeSDK(_sdk_types()):
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        messages = [message_start, sdk_result]

        class ClaudeSDKClient(_SDKClient):
            async def receive_response(self):
                for message in _FakeSDK.messages:
                    yield message

    executor = ClaudeSDKExecutor()
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=_FakeSDK):
        events = [
            e
            async for e in executor.run_turn(
                [{"role": "user", "content": "hi"}],
                [],
                "",
            )
        ]

    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert errors, "Expected an ExecutorError for the terminal failure"
    usage = errors[0].usage
    assert usage is not None, (
        "ExecutorError.usage is None — the observed message_start usage was "
        "discarded on the terminal-error path, so the context meter freezes."
    )
    # Window fill = input + cache_creation + cache_read from the last call.
    assert usage["context_tokens"] == 100_000
    # output_tokens is unknown on an incomplete turn — reported as 0.
    assert usage["output_tokens"] == 0


def _make_transport_with_process(returncode):
    """Fake ``SubprocessCLITransport`` whose child reports *returncode*."""

    class _Transport:
        def __init__(self):
            self._process = SimpleNamespace(returncode=returncode, pid=4242, wait=AsyncMock())
            self._stdout_stream = None
            self._stdin_stream = None
            self._stderr_stream = None
            self._stderr_task = None
            self._ready = returncode is None

    return _Transport()


def _make_recovery_fake_sdk():
    """Fake SDK whose clients record construction and queried prompts."""
    from claude_agent_sdk.types import (
        ClaudeAgentOptions as SDKClaudeAgentOptions,
    )
    from claude_agent_sdk.types import ResultMessage as SDKResultMessage
    from claude_agent_sdk.types import StreamEvent as SDKStreamEvent

    class _Sentinel:
        pass

    sdk_result = SDKResultMessage(
        subtype="result",
        session_id="s1",
        result="recovered",
        total_cost_usd=0.0,
        duration_ms=100,
        duration_api_ms=80,
        is_error=False,
        num_turns=1,
        usage={"input_tokens": 10, "output_tokens": 5},
    )

    class _FakeSDK:
        AssistantMessage = _Sentinel
        UserMessage = _Sentinel
        SystemMessage = _Sentinel
        StreamEvent = SDKStreamEvent
        ResultMessage = SDKResultMessage
        ClaudeAgentOptions = SDKClaudeAgentOptions
        created_clients = []

        class ClaudeSDKClient:
            def __init__(self, options):
                self.options = options
                self.prompts = []
                self._query = None
                self._transport = _make_transport_with_process(None)
                _FakeSDK.created_clients.append(self)

            async def connect(self):
                return None

            async def query(self, prompt, session_id="default"):
                self.prompts.append(prompt)

            async def receive_response(self):
                yield sdk_result

            async def set_model(self, model):
                return None

            async def disconnect(self):
                return None

    return _FakeSDK


@pytest.mark.asyncio
async def test_terminated_cli_client_is_evicted_and_turn_recovers() -> None:
    """Rebuild a cached client after its CLI child exits."""
    from omnigent.inner.claude_sdk_executor import (
        ClaudeSDKExecutor,
        _ClaudeClientState,
    )

    fake_sdk = _make_recovery_fake_sdk()
    executor = ClaudeSDKExecutor()

    dead_client = SimpleNamespace(
        _query=None,
        _transport=_make_transport_with_process(143),
        disconnect=AsyncMock(),
        query=AsyncMock(side_effect=AssertionError("dead client must not be queried")),
        set_model=AsyncMock(),
    )
    executor._clients["sess-1"] = _ClaudeClientState(client=dead_client, model=None)

    messages = [
        {"role": "user", "content": "first question", "session_id": "sess-1"},
        {"role": "assistant", "content": "first answer", "session_id": "sess-1"},
        {"role": "user", "content": "second question", "session_id": "sess-1"},
    ]
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [e async for e in executor.run_turn(messages, [], "")]

    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert not errors, f"Turn after a terminated CLI must recover, got: {errors}"
    assert any(isinstance(e, TurnComplete) for e in events)

    dead_client.query.assert_not_called()
    assert len(fake_sdk.created_clients) == 1
    fresh = fake_sdk.created_clients[0]
    assert executor._clients["sess-1"].client is fresh

    assert len(fresh.prompts) == 1
    prompt = fresh.prompts[0]
    assert isinstance(prompt, str)
    assert "first question" in prompt
    # The intervening assistant turn must be replayed too: the rebuilt client
    # has no session memory, so a user-only replay would drop its own answers.
    assert "first answer" in prompt
    assert "second question" in prompt

    assert "sess-1" not in executor._crashed_sessions


@pytest.mark.asyncio
async def test_live_cached_client_is_reused_between_turns() -> None:
    """Reuse a cached client while its CLI child is running."""
    from omnigent.inner.claude_sdk_executor import (
        ClaudeSDKExecutor,
        _ClaudeClientState,
    )

    fake_sdk = _make_recovery_fake_sdk()
    executor = ClaudeSDKExecutor()

    live_client = fake_sdk.ClaudeSDKClient(options=None)
    fake_sdk.created_clients.clear()
    executor._clients["sess-1"] = _ClaudeClientState(client=live_client, model=None)

    messages = [
        {"role": "user", "content": "first question", "session_id": "sess-1"},
        {"role": "assistant", "content": "first answer", "session_id": "sess-1"},
        {"role": "user", "content": "second question", "session_id": "sess-1"},
    ]
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [e async for e in executor.run_turn(messages, [], "")]

    assert any(isinstance(e, TurnComplete) for e in events)
    assert not [e for e in events if isinstance(e, ExecutorError)]

    assert fake_sdk.created_clients == []
    assert executor._clients["sess-1"].client is live_client
    assert live_client.prompts == ["second question"]


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_effort", [None, "low"])
@pytest.mark.parametrize(
    "compact_content",
    [
        None,
        "/compact",
        [{"type": "text", "text": "/compact"}],
        [{"type": "input_text", "text": "/compact"}],
    ],
)
async def test_effort_changes_rebuild_client_with_history(initial_effort, compact_content) -> None:
    """Changing or clearing effort reaches the next query without losing history."""
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor
    from omnigent.inner.executor import ExecutorConfig

    fake_sdk = _make_recovery_fake_sdk()
    executor = ClaudeSDKExecutor()
    messages = []
    efforts = [initial_effort, "max", "max", None]
    with (
        patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk),
        patch.object(executor, "_force_close_client", new_callable=AsyncMock) as close,
    ):
        for index, effort in enumerate(efforts):
            if index == 1:
                initial_client = executor._clients["effort"].client
                if compact_content is not None:
                    messages.append({"role": "user", "content": compact_content})
                    compact_events = [
                        event
                        async for event in executor.run_turn(
                            messages, [], "", ExecutorConfig(extra={"reasoning_effort": effort})
                        )
                    ]
                    assert not [
                        event for event in compact_events if isinstance(event, ExecutorError)
                    ]
                    assert executor._clients["effort"].client is initial_client
                    assert executor._clients["effort"].effort == initial_effort
                    assert initial_client.prompts[-1] == "/compact"
                    messages.append({"role": "assistant", "content": "compacted summary"})
                # No pending input must not replay an already-completed turn.
                query_count = len(initial_client.prompts)
                empty_events = [
                    event
                    async for event in executor.run_turn(
                        messages, [], "", ExecutorConfig(extra={"reasoning_effort": effort})
                    )
                ]
                assert empty_events == [TurnComplete(response=None)]
                assert executor._clients["effort"].client is initial_client
                assert len(initial_client.prompts) == query_count
                assert len(fake_sdk.created_clients) == 1
                close.assert_not_awaited()
            messages.append(
                {"role": "user", "content": f"question {index}", "session_id": "effort"}
            )
            events = [
                event
                async for event in executor.run_turn(
                    messages, [], "", ExecutorConfig(extra={"reasoning_effort": effort})
                )
            ]
            assert not [event for event in events if isinstance(event, ExecutorError)]
            assert any(isinstance(event, TurnComplete) for event in events)
            client = executor._clients["effort"].client
            assert client.options.effort == effort
            prompt = client.prompts[-1]
            if index == 2:
                assert prompt == "question 2"
            else:
                for previous in range(index):
                    assert f"question {previous}" in prompt
                    assert f"answer {previous}" in prompt
            messages.append({"role": "assistant", "content": f"answer {index}"})

    assert len(fake_sdk.created_clients) == 3
    assert [call.args[0] for call in close.await_args_list] == fake_sdk.created_clients[:2]


def test_tool_call_metadata_marks_only_omnigent_mcp_tools_as_dispatched() -> None:
    """Only the in-process ``omnigent`` MCP server's tools come back for dispatch.

    Claude Code's own tools and other MCP servers' tools run inside the CLI, so
    they are ``internally_executed`` and stay out of dispatch correlation.
    """
    from types import SimpleNamespace

    from omnigent.inner.claude_sdk_executor import _tool_call_metadata

    for name, internal in (
        ("mcp__omnigent__sys_os_shell", False),
        ("Skill", True),
        ("ToolSearch", True),
        ("mcp__github__create_issue", True),
    ):
        metadata = _tool_call_metadata(SimpleNamespace(id="toolu_1", name=name))  # type: ignore[arg-type]
        assert metadata == {"call_id": "toolu_1", "internally_executed": internal}, name


class TestAskUserQuestionHook(unittest.TestCase):
    """The in-process PreToolUse hook that renders AskUserQuestion as a
    clickable form and feeds answers back via ``updatedInput``."""

    def _fake_sdk(self):
        class HookMatcher:
            def __init__(self, matcher=None, timeout=None, hooks=None):
                self.matcher = matcher
                self.timeout = timeout
                self.hooks = hooks

        return SimpleNamespace(HookMatcher=HookMatcher)

    def _aq_matcher(self, options):
        for m in (getattr(options, "hooks", None) or {}).get("PreToolUse", []):
            if getattr(m, "matcher", None) == "AskUserQuestion":
                return m
        return None

    def _make_executor(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        return ClaudeSDKExecutor()

    def test_tool_and_hook_are_enabled_together(self):
        # Exposure and hook install share one predicate: the tool without its
        # intercept would hang on a headless picker.
        cases = [
            ("no-handler", False, True),
            ("no-hook-matcher", True, False),
            ("neither", False, False),
            ("handler-and-hook-matcher", True, True),
        ]
        for name, has_handler, has_hook_matcher in cases:
            with self.subTest(name):
                ex = self._make_executor()
                if has_handler:
                    ex._ask_question_handler = AsyncMock(return_value="unused")
                sdk = self._fake_sdk() if has_hook_matcher else SimpleNamespace()
                opts = SimpleNamespace(hooks=None)
                ex._install_ask_user_question_hook(sdk, opts)
                enabled = has_handler and has_hook_matcher
                self.assertEqual("AskUserQuestion" in ex._base_tools(sdk), enabled)
                self.assertEqual(self._aq_matcher(opts) is not None, enabled)

    def test_registers_matcher_with_long_human_timeout(self):
        from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

        ex = self._make_executor()
        ex._ask_question_handler = AsyncMock(return_value={"answers": {"q1": "a"}})
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        m = self._aq_matcher(opts)
        self.assertIsNotNone(m)
        self.assertEqual(m.timeout, ClaudeSDKExecutor._ASK_QUESTION_HOOK_TIMEOUT_S)

    def test_hook_allows_with_updated_input_on_answers(self):
        ex = self._make_executor()
        tool_input = {"questions": [{"question": "Env?", "options": ["dev", "prod"]}]}
        ex._ask_question_handler = AsyncMock(return_value={**tool_input, "answers": {"q1": "dev"}})
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        cb = self._aq_matcher(opts).hooks[0]
        out = _run(cb({"tool_input": tool_input}, "tuid", {}))
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["hookEventName"], "PreToolUse")
        self.assertEqual(hso["permissionDecision"], "allow")
        self.assertEqual(hso["updatedInput"], {**tool_input, "answers": {"q1": "dev"}})
        ex._ask_question_handler.assert_awaited_once_with(tool_input)

    def test_hook_denies_with_handler_reason(self):
        ex = self._make_executor()
        ex._ask_question_handler = AsyncMock(return_value="The user dismissed the question.")
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        cb = self._aq_matcher(opts).hooks[0]
        out = _run(cb({"tool_input": {}}, None, {}))
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertEqual(hso["permissionDecisionReason"], "The user dismissed the question.")

    def test_hook_runs_tool_call_policy_before_asking(self):
        # The PreToolUse allow skips can_use_tool, so a policy DENY must be
        # enforced here and the question never shown.
        from omnigent.runtime.harnesses._scaffold import PolicyVerdictPayload

        ex = self._make_executor()
        ex._ask_question_handler = AsyncMock(return_value={"answers": {"q1": "a"}})
        ex._policy_evaluator = AsyncMock(
            return_value=PolicyVerdictPayload(action="POLICY_ACTION_DENY", reason="no questions")
        )
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        cb = self._aq_matcher(opts).hooks[0]
        tool_input = {"questions": [{"question": "Q", "options": ["a"]}]}
        out = _run(cb({"tool_input": tool_input}, None, {}))
        hso = out["hookSpecificOutput"]
        self.assertEqual(hso["permissionDecision"], "deny")
        self.assertEqual(hso["permissionDecisionReason"], "no questions")
        ex._policy_evaluator.assert_awaited_once_with(
            "PHASE_TOOL_CALL", {"name": "AskUserQuestion", "arguments": tool_input}
        )
        ex._ask_question_handler.assert_not_awaited()

    def test_hook_denies_on_malformed_payload(self):
        # A non-dict PreToolUse payload can't yield a tool_input, so the hook
        # fails closed with an explicit deny (never falls through) and never
        # invokes the bridge — consistent with the handler-None deny path.
        ex = self._make_executor()
        ex._ask_question_handler = AsyncMock(return_value={"answers": {"q1": "a"}})
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        cb = self._aq_matcher(opts).hooks[0]
        out = _run(cb("not-a-dict", None, {}))
        self.assertEqual(out["hookSpecificOutput"]["permissionDecision"], "deny")
        ex._ask_question_handler.assert_not_awaited()

    def test_hook_denies_when_policy_or_handler_raises(self):
        # A raised hook reaches the CLI as "no opinion" and falls back to
        # native handling, so failures must become an explicit deny.
        from omnigent.runtime.harnesses._scaffold import PolicyVerdictPayload

        allow = PolicyVerdictPayload(action="POLICY_ACTION_ALLOW", reason="")
        cases = [
            ("policy-raises", AsyncMock(side_effect=RuntimeError("policy down")), None),
            ("handler-raises", AsyncMock(return_value=allow), RuntimeError("bridge down")),
        ]
        for name, policy_evaluator, handler_error in cases:
            with self.subTest(name):
                ex = self._make_executor()
                ex._policy_evaluator = policy_evaluator
                ex._ask_question_handler = AsyncMock(
                    side_effect=handler_error, return_value={"answers": {"q1": "a"}}
                )
                opts = SimpleNamespace(hooks=None)
                ex._install_ask_user_question_hook(self._fake_sdk(), opts)
                cb = self._aq_matcher(opts).hooks[0]
                with self.assertLogs("omnigent.inner.claude_sdk_executor", "ERROR"):
                    out = _run(cb({"tool_input": {"questions": []}}, None, {}))
                hso = out["hookSpecificOutput"]
                self.assertEqual(hso["permissionDecision"], "deny")
                self.assertEqual(
                    hso["permissionDecisionReason"],
                    "AskUserQuestion failed in Coral; ask in plain text instead.",
                )

    def test_hook_lets_cancellation_propagate(self):
        # Turn cancellation must unwind the hook, not be swallowed as a deny.
        ex = self._make_executor()
        ex._ask_question_handler = AsyncMock(side_effect=asyncio.CancelledError())
        opts = SimpleNamespace(hooks=None)
        ex._install_ask_user_question_hook(self._fake_sdk(), opts)
        cb = self._aq_matcher(opts).hooks[0]
        with self.assertRaises(asyncio.CancelledError):
            _run(cb({"tool_input": {"questions": []}}, None, {}))


@pytest.mark.parametrize("bridge_wired", [False, True], ids=["no-bridge", "bridge"])
async def test_turn_options_expose_ask_user_question_only_with_its_hook(
    bridge_wired: bool,
) -> None:
    # A built turn must expose the tool and install its intercept together:
    # the tool without the hook would hang on a headless picker.
    executor = _default_executor()
    if bridge_wired:
        executor._ask_question_handler = AsyncMock(return_value="unused")

    options = await _turn_options(executor)

    matchers = [m.matcher for m in (options.hooks or {}).get("PreToolUse", [])]
    assert ("AskUserQuestion" in options.tools) is bridge_wired
    assert ("AskUserQuestion" in matchers) is bridge_wired


# CORAL(S13): Coral specs refuse subscription auth and missing OS sandboxes before the CLI starts.


def _coral_executor(monkeypatch, **kwargs):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor._find_system_claude", lambda: None)
    return ClaudeSDKExecutor(**kwargs)


async def _turn_with_recording_sdk(executor):
    """Run one turn on a fake SDK; return its events, the SDK and each client's spawn env."""
    fake_sdk = _make_recovery_fake_sdk()
    spawn_envs = []

    class _RecordingClient(fake_sdk.ClaudeSDKClient):
        async def connect(self):
            spawn_envs.append({**os.environ, **(getattr(self.options, "env", None) or {})})

    fake_sdk.ClaudeSDKClient = _RecordingClient
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [e async for e in executor.run_turn([{"role": "user", "content": "hi"}], [], "")]
    return events, fake_sdk, spawn_envs


async def test_coral_spec_without_api_credential_is_refused_before_the_cli(monkeypatch):
    from omnigent.inner.claude_sdk_executor import (
        CORAL_SUBSCRIPTION_AUTH_REFUSED_CODE,
        CORAL_SUBSCRIPTION_AUTH_REFUSED_MESSAGE,
    )

    executor = _coral_executor(monkeypatch, require_api_credential=True)

    events, fake_sdk, spawn_envs = await _turn_with_recording_sdk(executor)

    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert len(errors) == 1 and len(events) == 1
    assert errors[0].code == CORAL_SUBSCRIPTION_AUTH_REFUSED_CODE
    assert errors[0].retryable is False
    assert errors[0].message == CORAL_SUBSCRIPTION_AUTH_REFUSED_MESSAGE
    assert "Claude Code" not in errors[0].message
    assert fake_sdk.created_clients == []
    assert spawn_envs == []


@pytest.mark.parametrize(
    "credential",
    [
        {"api_key_helper": "printf %s sk-ant-test"},
        {
            "gateway": True,
            "gateway_host": "https://gateway.example",
            "base_url_override": "https://gateway.example/anthropic",
            "gateway_auth_command": "printf %s gateway-token",
        },
    ],
    ids=["api-key-helper", "gateway"],
)
async def test_coral_spec_with_api_credential_reaches_the_cli(monkeypatch, credential):
    executor = _coral_executor(monkeypatch, require_api_credential=True, **credential)
    if credential.get("gateway"):
        monkeypatch.setattr(
            executor, "_apply_gateway_model_vocabulary", AsyncMock(return_value={})
        )
        monkeypatch.setattr(executor, "_route_options_through_gateway_shim", AsyncMock())

    events, fake_sdk, _ = await _turn_with_recording_sdk(executor)

    assert not [e for e in events if isinstance(e, ExecutorError)], events
    assert any(isinstance(e, TurnComplete) for e in events)
    assert len(fake_sdk.created_clients) == 1


async def test_non_coral_spec_without_api_credential_keeps_subscription_auth(monkeypatch):
    executor = _coral_executor(monkeypatch)

    events, fake_sdk, _ = await _turn_with_recording_sdk(executor)

    assert not [e for e in events if isinstance(e, ExecutorError)], events
    assert any(isinstance(e, TurnComplete) for e in events)
    assert len(fake_sdk.created_clients) == 1


@pytest.mark.parametrize(("coral", "token_seen"), [(True, False), (False, True)])
async def test_coral_spec_cli_never_sees_subscription_tokens(monkeypatch, coral, token_seen):
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "inherited-oauth")
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._claude_user_settings_env",
        lambda cwd=None: {"ANTHROPIC_AUTH_TOKEN": "settings-token"},
    )
    executor = _coral_executor(
        monkeypatch,
        require_api_credential=coral,
        api_key_helper="printf %s sk-ant-test",
        skills_filter="none",
    )

    events, _, spawn_envs = await _turn_with_recording_sdk(executor)

    assert any(isinstance(e, TurnComplete) for e in events)
    assert len(spawn_envs) == 1
    assert ("CLAUDE_CODE_OAUTH_TOKEN" in spawn_envs[0]) is token_seen
    assert ("ANTHROPIC_AUTH_TOKEN" in spawn_envs[0]) is token_seen
    assert os.environ["CLAUDE_CODE_OAUTH_TOKEN"] == "inherited-oauth"


# CORAL(S118): the host forwards these to a harness; a Coral harness's CLI gets none of them.
@pytest.mark.parametrize(
    "host_env",
    [
        {"MY_KEY": "<key>"},
        {"OMNIGENT_ANTHROPIC_API_KEY": "<host secret>"},
        {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_BEARER_TOKEN_BEDROCK": "<host secret>"},
    ],
    ids=["env-ref-key", "omnigent-prefixed-key", "bedrock-host-env"],
)
async def test_coral_harness_cli_env_holds_no_forwarded_credential(
    monkeypatch, tmp_path, host_env
):
    import secrets
    import shlex

    from omnigent.inner import claude_sdk_harness

    key = f"sk-ant-test-{secrets.token_hex(16)}"
    host_secret = f"sk-ant-test-{secrets.token_hex(16)}"
    values = {"<key>": key, "<host secret>": host_secret}
    host_env = {name: values.get(value, value) for name, value in host_env.items()}
    environ = {
        "PATH": os.defpath,
        "HOME": str(tmp_path),
        "HARNESS_CLAUDE_SDK_REQUIRE_API_CREDENTIAL": "1",
        "HARNESS_CLAUDE_SDK_API_KEY_HELPER": f"printf %s {shlex.quote(key)}",
        **host_env,
    }
    monkeypatch.setattr(os, "environ", environ)
    monkeypatch.setattr(claude_sdk_harness, "IS_POSIX", True)
    # The subject is the CLI's environment, so this turn needs no OS sandbox.
    monkeypatch.setattr(claude_sdk_harness, "_resolve_os_env", lambda config: None)
    monkeypatch.setattr("omnigent.inner.claude_sdk_executor._find_system_claude", lambda: None)
    factories = []
    real_adapter = claude_sdk_harness.ExecutorAdapter

    def recording_adapter(*, executor_factory, **kwargs):
        factories.append(executor_factory)
        return real_adapter(executor_factory=executor_factory, **kwargs)

    monkeypatch.setattr(claude_sdk_harness, "ExecutorAdapter", recording_adapter)
    claude_sdk_harness.create_app()

    # The first build and a rebuild from the same factory.
    for executor in (factories[0](), factories[0]()):
        events, fake_sdk, spawn_envs = await _turn_with_recording_sdk(executor)

        assert any(isinstance(e, TurnComplete) for e in events), events
        (client,) = fake_sdk.created_clients
        for env in (spawn_envs[0], client.options.env):
            assert sorted(set(host_env) & set(env)) == []
            assert sorted(name for name in env if name.startswith("HARNESS_CLAUDE_SDK_")) == []
            assert sorted(name for name, v in env.items() if key in v or host_secret in v) == []


@pytest.mark.parametrize(
    ("sandbox_type", "binary_present"),
    [(None, True), ("none", True), ("windows_jobobject", True), ("linux_bwrap", False)],
    ids=["no-sandbox", "none", "windows-jobobject", "bwrap-missing"],
)
async def test_coral_spec_without_os_sandbox_is_refused(monkeypatch, sandbox_type, binary_present):
    from omnigent.inner.claude_sdk_executor import CORAL_SANDBOX_UNAVAILABLE_CODE
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    sandbox = OSEnvSandboxSpec(type=sandbox_type) if sandbox_type is not None else None
    executor = _coral_executor(
        monkeypatch,
        require_api_credential=True,
        api_key_helper="printf %s sk-ant-test",
        os_env=OSEnvSpec(cwd=str(Path.cwd()), sandbox=sandbox),
    )
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.shutil.which",
        lambda name: f"/usr/bin/{name}" if binary_present else None,
    )

    events, fake_sdk, _ = await _turn_with_recording_sdk(executor)

    assert [e.code for e in events if isinstance(e, ExecutorError)] == [
        CORAL_SANDBOX_UNAVAILABLE_CODE
    ]
    assert fake_sdk.created_clients == []


@pytest.mark.parametrize("sandbox_type", ["linux_bwrap", "darwin_seatbelt"])
async def test_coral_spec_with_os_sandbox_reaches_the_cli(monkeypatch, sandbox_type):
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    executor = _coral_executor(
        monkeypatch,
        require_api_credential=True,
        api_key_helper="printf %s sk-ant-test",
        os_env=OSEnvSpec(cwd=str(Path.cwd()), sandbox=OSEnvSandboxSpec(type=sandbox_type)),
    )
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.shutil.which", lambda name: f"/usr/bin/{name}"
    )

    events, fake_sdk, _ = await _turn_with_recording_sdk(executor)

    assert not [e for e in events if isinstance(e, ExecutorError)], events
    assert len(fake_sdk.created_clients) == 1


# CORAL(S113): an isolated CLI gets only a private config dir, and starts only in its sandbox.
_CONFIG_NAMES = ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR")


def _isolation_executor(monkeypatch, tmp_path: Path, *, cli: str | None, os_env=None, **kwargs):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setattr("omnigent.inner.claude_sdk_executor._find_system_claude", lambda: cli)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.shutil.which", lambda name: f"/usr/bin/{name}"
    )
    # CORAL(S115): a test may name its own skills or credential
    options = {"api_key_helper": "printf %s sk-ant-test", "skills_filter": "none", **kwargs}
    return ClaudeSDKExecutor(os_env=os_env, **options)


# tight-*: no os_env; the tight wrap returns a launcher on Linux, the real CLI on macOS or a fault.
# off-host: the names come from the host's environment only, not the user's settings.
@pytest.mark.parametrize(
    "mode", ["wrapped", "unwrapped", "tight-wrapped", "tight-unwrapped", "off", "off-host"]
)
async def test_an_isolated_cli_gets_only_its_own_claude_config_dir(monkeypatch, tmp_path, mode):
    """Neither name reaches an isolated CLI from the environment or the user's settings."""
    from omnigent.inner.claude_sdk_executor import PreparedClaudeCli
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    off = mode.startswith("off")
    user_dir = str(tmp_path / "user-claude")
    for name in _CONFIG_NAMES:
        monkeypatch.setenv(name, user_dir)
    settings = {} if mode == "off-host" else dict.fromkeys(_CONFIG_NAMES, "settings-dir")
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._claude_user_settings_env", lambda cwd=None: settings
    )
    launcher = PreparedClaudeCli(str(tmp_path / "launcher"), True, config_isolated=True)
    asked: list[bool] = []

    def _prepare(cli, spec, *, isolate_config=False, config_seed=None):  # CORAL(S115): seed
        asked.append(isolate_config)
        return launcher

    def _prepare_tight(cli, *, cwd=None, isolate_config=False, config_seed=None):
        asked.append(isolate_config)
        return launcher.cli_path if mode == "tight-wrapped" else cli

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.prepare_claude_cli_path", _prepare)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.prepare_tight_cli_process_path", _prepare_tight
    )
    wrapped = mode in ("wrapped", "tight-wrapped")
    no_cli = mode == "unwrapped" or off
    executor = _isolation_executor(
        monkeypatch,
        tmp_path,
        cli=None if no_cli else "/usr/bin/claude",
        os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec())
        if mode == "wrapped"
        else None,
        isolate_claude_config=not off,
    )

    events, _, spawn_envs = await _turn_with_recording_sdk(executor)
    [spawn_env] = spawn_envs
    own = spawn_env.get("CLAUDE_CONFIG_DIR")
    own_dir = Path(own) if own and mode in ("unwrapped", "tight-unwrapped") else None
    private = own_dir is not None and own_dir.is_absolute() and _is_private(own_dir)
    await executor.close()

    assert any(isinstance(e, TurnComplete) for e in events), events
    assert [os.environ[name] for name in _CONFIG_NAMES] == [user_dir, user_dir]
    assert asked == ([] if no_cli else [True]), "the wrap was not asked to isolate"
    if off:
        kept = [user_dir] * 2 if mode == "off-host" else ["settings-dir"] * 2
        assert [spawn_env.get(name) for name in _CONFIG_NAMES] == kept
        return
    store = spawn_env.get("CLAUDE_SECURESTORAGE_CONFIG_DIR")
    if wrapped:
        # The launcher sets both in the wrap.
        assert (own, store) == (None, None)
    else:
        assert private, f"the unwrapped CLI's config dir is not its own private dir: {own}"
        assert store == own and own_dir is not None and not own_dir.exists()


def _is_private(path: Path) -> bool:
    """A 0700 dir whose ``projects`` is a file, so the CLI cannot spill tool results there."""
    return (path.stat().st_mode & 0o777) == 0o700 and (path / "projects").is_file()


@pytest.mark.parametrize(
    ("fault", "refused"),
    [
        ("no-system-claude", True),
        ("resolve-fails", True),
        ("probe-fails", True),
        ("inactive", True),
        ("operator-opt-out", False),
        ("network-off", False),
    ],
)
async def test_an_isolated_cli_its_sandbox_cannot_wrap_never_starts(
    monkeypatch, tmp_path, fault, refused
):
    """A wrap that fails is refused; an unwrapped CLI by design runs on its own config dir."""
    from omnigent.inner.claude_sdk_executor import CORAL_SANDBOX_UNAVAILABLE_CODE
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    monkeypatch.setattr(  # never read the caller's real Claude settings
        "omnigent.inner.claude_sdk_executor._claude_user_settings_env", lambda cwd=None: {}
    )
    if fault != "no-system-claude":
        _break_wrap(monkeypatch, fault)
    sandbox = OSEnvSandboxSpec(type="linux_bwrap", allow_network=fault != "network-off")
    executor = _isolation_executor(
        monkeypatch,
        tmp_path,
        cli=None if fault == "no-system-claude" else "/usr/bin/claude",
        os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=sandbox),
        require_api_credential=True,
        isolate_claude_config=True,
    )

    events, fake_sdk, spawn_envs = await _turn_with_recording_sdk(executor)
    await executor.close()

    errors = [e for e in events if isinstance(e, ExecutorError)]
    if refused:
        assert [(e.code, e.retryable) for e in errors] == [(CORAL_SANDBOX_UNAVAILABLE_CODE, False)]
        assert "cannot run in its OS sandbox" in errors[0].message
        assert fake_sdk.created_clients == []
    else:
        assert errors == [] and len(spawn_envs) == 1
        assert spawn_envs[0]["CLAUDE_CONFIG_DIR"].startswith(tempfile.gettempdir())


async def test_a_concurrent_connect_cannot_hand_a_cli_the_hosts_config_names(
    monkeypatch, tmp_path
):
    """
    One connect restores the host's values while another is still connecting. The second
    CLI still gets only the private dir, because the options name it under both names.
    """
    user_dir = str(tmp_path / "user-claude")
    for name in _CONFIG_NAMES:
        monkeypatch.setenv(name, user_dir)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._claude_user_settings_env", lambda cwd=None: {}
    )
    executor = _isolation_executor(monkeypatch, tmp_path, cli=None, isolate_claude_config=True)
    fake_sdk = _make_recovery_fake_sdk()
    second_connecting, first_returning = asyncio.Event(), asyncio.Event()
    seen: dict[str, tuple[str | None, dict[str, str]]] = {}

    class _RacingClient(fake_sdk.ClaudeSDKClient):
        async def connect(self):
            role = "second" if second_connecting.is_set() or "first" in seen else "first"
            seen.setdefault(role, (None, {}))
            if role == "first":
                await second_connecting.wait()
            else:
                second_connecting.set()
                # The first connect returns, and restores the host's values, before this resumes.
                await first_returning.wait()
            spawn_env = {**os.environ, **(self.options.env or {})}
            seen[role] = (os.environ.get("CLAUDE_SECURESTORAGE_CONFIG_DIR"), spawn_env)
            if role == "first":
                first_returning.set()

    async def _turn(session_id: str) -> list:
        messages = [{"role": "user", "content": "hi", "session_id": session_id}]
        return [event async for event in executor.run_turn(messages, [], "")]

    fake_sdk.ClaudeSDKClient = _RacingClient
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        turns = await asyncio.gather(_turn("first"), _turn("second"))
    private = str(executor._unwrapped_claude_config_dir)
    await executor.close()

    assert all(any(isinstance(e, TurnComplete) for e in events) for events in turns), turns
    (first_host_value, first_env), (second_host_value, second_env) = seen["first"], seen["second"]
    # The first CLI spawned inside its unset window; the second after the first's restore.
    assert (first_host_value, second_host_value) == (None, user_dir), "the race did not happen"
    for env in (first_env, second_env):
        assert [env.get(name) for name in _CONFIG_NAMES] == [private, private]
    assert [os.environ[name] for name in _CONFIG_NAMES] == [user_dir, user_dir]


# CORAL(S115): a wrapped non-Coral CLI's private dir starts from a filtered copy of the user's
# global config, written only just before each launch.
_SEED_SERVERS = {
    "local": {"type": "stdio", "command": "srv", "env": {"TOKEN": "throwaway-secret"}},
    "remote": {"type": "http", "url": "https://mcp.example.test"},
}
_SEED_PROJECT = {
    "hasTrustDialogAccepted": True,
    "hasClaudeMdExternalIncludesApproved": True,
    "disabledMcpServers": ["remote"],
    "enabledMcpServers": ["computer-use"],
    "disabledMcpjsonServers": ["planted"],
    "enabledMcpjsonServers": ["repo-tool"],
    "enableAllProjectMcpServers": True,
}
# The value the CLI treats as unset, for each kept key (2.1.325); none of these is copied.
_UNSET_PROJECT = {
    "hasTrustDialogAccepted": False,
    "hasClaudeMdExternalIncludesApproved": False,
    "disabledMcpServers": [],
    "enabledMcpServers": [],
    "disabledMcpjsonServers": [],
    "enabledMcpjsonServers": [],
    "enableAllProjectMcpServers": False,
}


def _user_claude_config(**extra) -> dict:
    """A global config with every kind of key the seed keeps or drops."""
    return {
        "mcpServers": _SEED_SERVERS,
        "userID": "throwaway-user",
        "env": {
            "HTTPS_PROXY": "http://proxy.example.test",
            "RETRIES": 3,
            "CLAUDE_CONFIG_DIR": "/elsewhere",
            "CLAUDE_SECURESTORAGE_CONFIG_DIR": "",
        },
        "oauthAccount": {"emailAddress": "user@example.test"},
        "primaryApiKey": "sk-ant-throwaway",
        "customApiKeyResponses": {"approved": ["throwaway"]},
        "numStartups": 7,
        "cachedGrowthBookFeatures": {"flag": True},
        "projects": {
            "/work/repo": {
                **_SEED_PROJECT,
                "mcpServers": {"local-only": {"command": "x", "env": {"KEY": "throwaway"}}},
                "allowedTools": ["Bash"],
                "lastSessionId": "s",
            },
            "/work/other": {"hasTrustDialogAccepted": True, "lastCost": 1.5},
            "/work/mixed": {**_UNSET_PROJECT, "disabledMcpServers": ["remote"]},
            "/work/visited": {**_UNSET_PROJECT, "projectOnboardingSeenCount": 1},
            "/work/empty": {"mcpServers": {"x": {}}, "history": []},
            "/work/odd": ["not", "an", "entry"],
        },
        **extra,
    }


_EXPECTED_SEED = {
    "mcpServers": _SEED_SERVERS,
    "userID": "throwaway-user",
    "env": {"HTTPS_PROXY": "http://proxy.example.test"},
    "projects": {
        "/work/repo": _SEED_PROJECT,
        "/work/other": {"hasTrustDialogAccepted": True},
        "/work/mixed": {"disabledMcpServers": ["remote"]},
    },
}


def test_the_seed_keeps_only_mcp_identity_env_and_project_trust_keys(
    tmp_path, monkeypatch, claude_config_seed_source
) -> None:
    """
    No credential, OAuth account, cache, project MCP server, other project key, key at its
    unset value, project left empty or config dir name in ``env`` is copied, and the CLI's
    credential file is never opened, by any of the open calls: only the global config is read.
    """
    import builtins
    import io

    from omnigent.inner.claude_sdk_executor import _claude_config_seed

    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude.json").write_text(json.dumps(_user_claude_config()))
    credentials = home / ".claude" / ".credentials.json"
    credentials.write_text(json.dumps({"claudeAiOauth": {"accessToken": "x"}, "mcpOAuth": {}}))
    opened: list[str] = []

    def _spy(module, name):
        real = getattr(module, name)

        def _recording(path, *args, **kwargs):
            if not isinstance(path, int):  # os.fdopen hands io.open a descriptor
                opened.append(os.fspath(path))
            return real(path, *args, **kwargs)

        monkeypatch.setattr(module, name, _recording)

    for module, name in ((os, "open"), (builtins, "open"), (io, "open")):
        _spy(module, name)

    seed = _claude_config_seed({"HOME": str(home)})

    assert seed == _EXPECTED_SEED
    assert opened == [str(home / ".claude.json")], "the seed read something else"
    assert "claudeAiOauth" not in json.dumps(seed) and "mcpOAuth" not in json.dumps(seed)


@pytest.mark.parametrize(
    ("layout", "config_dir", "home_value", "read"),
    [
        ("home", None, "home", "home/.claude.json"),
        ("config-dir", "cfg", "home", "cfg/.claude.json"),
        ("legacy-home", None, "home", "home/.claude/.config.json"),
        ("legacy-config-dir", "cfg", "home", "cfg/.config.json"),
        ("symlinked-home", None, "home", "dotfiles/claude.json"),
        ("relative-config-dir", "relative", "home", None),
        ("empty-config-dir", "", "home", None),
        ("relative-home", None, "relative", None),
    ],
)
def test_the_seed_follows_the_clis_config_path_but_never_a_relative_one(
    tmp_path, caplog, claude_config_seed_source, layout, config_dir, home_value, read
) -> None:
    """A relative or empty config dir, which the CLI resolves in its cwd, gives no seed."""
    from omnigent.inner.claude_sdk_executor import _claude_config_seed

    for relative in ("home/.claude.json", "cfg/.claude.json", "relative/.claude.json"):
        (tmp_path / relative).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / relative).write_text(json.dumps({"userID": relative}))
    if layout.startswith("legacy"):
        legacy = tmp_path / (read or "")
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({"userID": read}))
    elif layout == "symlinked-home":  # a dotfiles repo links ~/.claude.json; the host follows it
        (tmp_path / "dotfiles").mkdir()
        (tmp_path / "dotfiles" / "claude.json").write_text(json.dumps({"userID": read}))
        (tmp_path / "home" / ".claude.json").unlink()
        (tmp_path / "home" / ".claude.json").symlink_to(tmp_path / "dotfiles" / "claude.json")
    env = {"HOME": str(tmp_path / "home") if home_value == "home" else home_value}
    if config_dir is not None:
        env["CLAUDE_CONFIG_DIR"] = (
            str(tmp_path / config_dir) if config_dir == "cfg" else config_dir
        )

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        seed = _claude_config_seed(env)

    assert seed == ({"userID": read} if read else {})
    refused = [r.getMessage() for r in caplog.records if "must be absolute" in r.getMessage()]
    assert bool(refused) is (read is None), (
        f"refused a valid source: {refused}" if read else "a relative source was not refused"
    )


# CORAL(S115): a test that builds an executor may inherit the developer's CLAUDE_CONFIG_DIR;
# the autouse fixture keeps its seed empty unless it opts in.
def test_a_test_that_does_not_opt_in_never_reads_a_claude_config(tmp_path) -> None:
    from omnigent.inner.claude_sdk_executor import _claude_config_seed

    (tmp_path / ".claude.json").write_text(json.dumps({"userID": "not-for-tests"}))
    assert _claude_config_seed({"HOME": str(tmp_path)}) == {}, "the hermetic fixture is off"


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    ("content", "warns", "cap"),
    [
        (None, False, None),
        ("{not json", True, None),
        ("[1, 2]", True, None),
        (b"\xff\xfe", True, None),
        ("fifo", True, None),
        ("[" * 100_000 + "]" * 100_000, True, None),  # CORAL(S115): past the recursion limit
        ('{"userID": "x"}' + " " * 100, True, 64),  # valid, but over a lowered size cap
    ],
    ids=["missing", "malformed", "not-an-object", "not-utf8", "fifo", "too-deep", "oversized"],
)
def test_a_missing_or_unusable_user_config_gives_an_empty_seed(
    tmp_path, monkeypatch, caplog, claude_config_seed_source, content, warns, cap
) -> None:
    """
    Never the real file, never a hang: an empty seed, with a warning naming the file. A config
    too deep to parse or past the size cap counts as malformed, and its warning names only the
    file.
    """
    from omnigent.inner.claude_sdk_executor import _claude_config_seed

    if cap is not None:
        monkeypatch.setattr(
            "omnigent.inner.claude_sdk_executor._CLAUDE_SEED_SOURCE_MAX_BYTES", cap
        )
    source = tmp_path / ".claude.json"
    if content == "fifo":
        os.mkfifo(source)
    elif isinstance(content, bytes):
        source.write_bytes(content)
    elif content is not None:
        source.write_text(content)

    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        assert _claude_config_seed({"HOME": str(tmp_path)}) == {}
    messages = [record.getMessage() for record in caplog.records]
    assert [str(source) in message for message in messages] == ([True] if warns else []), messages
    assert not any("recursion" in message for message in messages), messages


def _seed_prepare_stubs(monkeypatch, tmp_path: Path, *, wrapped: bool) -> list[dict]:
    """Stub both wraps; record what the executor asks each for. Seeds go under *tmp_path*."""
    from omnigent.inner.claude_sdk_executor import PreparedClaudeCli

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    asked: list[dict] = []
    launcher = str(tmp_path / "launcher")

    def _prepare(cli, spec, *, isolate_config=False, config_seed=None):
        asked.append({"isolate": isolate_config, "seed": config_seed})
        return PreparedClaudeCli(launcher if wrapped else cli, True, config_isolated=wrapped)

    def _prepare_tight(cli, *, cwd=None, isolate_config=False, config_seed=None):
        asked.append({"isolate": isolate_config, "seed": config_seed})
        return launcher if wrapped else cli

    monkeypatch.setattr("omnigent.inner.claude_sdk_executor.prepare_claude_cli_path", _prepare)
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor.prepare_tight_cli_process_path", _prepare_tight
    )
    return asked


@pytest.mark.parametrize(
    ("coral", "skills", "tight", "wrapped", "isolate", "seeded"),
    [
        (True, "all", False, True, True, False),
        (False, "all", False, True, None, True),
        (False, ["review"], False, True, None, True),
        (False, "bogus", False, True, None, True),
        (False, "none", False, True, None, False),
        (False, "all", False, False, None, False),
        (False, "all", True, True, True, True),
        (False, "all", True, False, True, False),
    ],
    ids=["coral", "all", "list", "malformed", "none", "unwrapped", "tight", "tight-unwrapped"],
)
async def test_only_a_wrapped_non_coral_cli_that_loads_user_settings_reads_the_users_config(
    monkeypatch, tmp_path, coral, skills, tight, wrapped, isolate, seeded
) -> None:
    """
    Nothing is read or made at construction; the seed is written once per launch, only for a
    wrapped non-Coral CLI whose skills load user settings. Others never read the user's config.
    """
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    asked = _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=wrapped)
    reads: list[object] = []
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._claude_config_seed",
        lambda env: reads.append(env) or {"userID": "throwaway"},
    )
    executor = _isolation_executor(
        monkeypatch,
        tmp_path,
        cli="/usr/bin/claude",
        os_env=None if tight else OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec()),
        skills_filter=skills,
        isolate_claude_config=coral,
    )
    [request] = asked
    seed = executor._claude_config_seed_path
    assert request["isolate"] is isolate
    assert (request["seed"] is not None) is (not coral and skills != "none")
    assert seed == (request["seed"] if seeded else None)
    assert reads == [] and not any(tmp_path.glob("**/claude.json"))
    if request["seed"] is not None:
        assert not request["seed"].parent.exists(), "construction made the seed dir"

    events, _, _ = await _turn_with_recording_sdk(executor)
    assert any(isinstance(e, TurnComplete) for e in events), events
    assert len(reads) == int(seeded)
    if seed is not None:
        assert json.loads(seed.read_text()) == {"userID": "throwaway"}
    await executor.close()
    assert seed is None or not seed.parent.exists()


async def _seeded_turn(executor, session_id: str, seen: list) -> list:
    """One turn on a new or live client; each launch records the seed it would copy."""
    fake_sdk = _make_recovery_fake_sdk()
    seed = executor._claude_config_seed_path

    class _SeedReadingClient(fake_sdk.ClaudeSDKClient):
        async def connect(self):
            info, folder = seed.stat(), seed.parent.stat()
            seen.append(
                (json.loads(seed.read_text()), info.st_mode & 0o777, folder.st_mode & 0o777)
            )

    fake_sdk.ClaudeSDKClient = _SeedReadingClient
    messages = [{"role": "user", "content": "hi", "session_id": session_id}]
    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        return [event async for event in executor.run_turn(messages, [], "")]


async def test_each_launch_gets_a_fresh_copy_and_a_closed_executor_launches_none(
    monkeypatch, tmp_path, claude_config_seed_source
) -> None:
    """
    A server the user adds reaches the next launch, not a live client. The dir is 0700 and the
    file 0600; close and ``__del__`` remove them, and a later launch fails instead of making
    the dir again.
    """
    from omnigent.inner.claude_sdk_executor import _claude_config_seed
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
    from omnigent.native.owner_claim import read_owner_claim  # CORAL(S116)

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    (home / ".claude.json").write_text(json.dumps(_user_claude_config()))
    _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=True)
    spec = OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec())
    executor = _isolation_executor(
        monkeypatch, tmp_path, cli="/usr/bin/claude", os_env=spec, skills_filter="all"
    )
    seed = executor._claude_config_seed_path
    seen: list = []

    await _seeded_turn(executor, "first", seen)
    added = _user_claude_config(mcpServers={**_SEED_SERVERS, "added": {"command": "new"}})
    (home / ".claude.json").write_text(json.dumps(added))
    await _seeded_turn(executor, "first", seen)
    # CORAL(S115): as a temp cleaner would; the next launch makes the dir again
    shutil.rmtree(seed.parent)  # CORAL(S116): with its owner claim
    await _seeded_turn(executor, "second", seen)

    assert [entry[1:] for entry in seen] == [(0o600, 0o700)] * 2
    assert seen[0][0] == _EXPECTED_SEED
    assert seen[1][0] == _claude_config_seed({"HOME": str(home)}) != seen[0][0]
    # CORAL(S116): the remade dir names this process, so a killed harness's seed is swept
    assert sorted(path.name for path in seed.parent.iterdir()) == [".launch-owner", seed.name]
    claim = read_owner_claim(seed.parent, filename=".launch-owner")
    assert claim is not None and claim.pid == os.getpid()
    await executor.close()
    assert not seed.parent.exists()
    with pytest.raises(RuntimeError, match="the executor is closed"):
        await _seeded_turn(executor, "third", seen)
    assert not seed.parent.exists() and len(seen) == 2

    other = _isolation_executor(
        monkeypatch, tmp_path, cli="/usr/bin/claude", os_env=spec, skills_filter="all"
    )
    await _seeded_turn(other, "first", seen)
    assert other._claude_config_seed_path.exists()
    other.__del__()
    assert not other._claude_config_seed_path.parent.exists()


# CORAL(S115): first-launch: planted before the dir was made; the others after a temp cleaner
# removed it
@pytest.mark.parametrize("planted", ["first-launch", "symlink", "foreign-owner", "group-readable"])
async def test_a_seed_dir_someone_else_made_fails_the_launch(
    monkeypatch, tmp_path, planted
) -> None:
    """
    The dir is made exclusively, so a planted one is never adopted. Once made, a dir found
    there must still be this user's own 0700 dir; a link or any other dir fails the launch.
    """
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=True)
    executor = _isolation_executor(
        monkeypatch,
        tmp_path,
        cli="/usr/bin/claude",
        os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec()),
        skills_filter="all",
    )
    seed, elsewhere = executor._claude_config_seed_path, tmp_path / "elsewhere"
    # CORAL(S115): a temp cleaner removes the dir this executor made, then a dir is planted
    if planted != "first-launch":
        await _seeded_turn(executor, "first", [])
        shutil.rmtree(seed.parent)  # CORAL(S116): with its owner claim
    elsewhere.mkdir(mode=0o700)
    if planted == "symlink":
        seed.parent.symlink_to(elsewhere)
    else:
        seed.parent.mkdir(mode=0o700)
        seed.parent.chmod(0o750 if planted == "group-readable" else 0o700)
    if planted == "foreign-owner":
        uid = os.getuid()
        monkeypatch.setattr("omnigent.inner.sandbox.os.getuid", lambda: uid + 1)

    with pytest.raises(RuntimeError, match="could not get its private Claude config"):
        await _seeded_turn(executor, "next", [])
    assert "next" not in executor._clients
    assert not any(elsewhere.iterdir()) and not seed.exists()


# CORAL(S116): a killed harness's unwrapped config dir names its owner, so a sweep removes it
def test_the_unwrapped_config_dir_names_its_owner(monkeypatch, tmp_path) -> None:
    from omnigent.native.owner_claim import read_owner_claim

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    executor = _isolation_executor(monkeypatch, tmp_path, cli=None, isolate_claude_config=True)

    path = executor._claude_config_dir_for_unwrapped_cli()

    assert path.parent == tmp_path
    assert getattr(read_owner_claim(path, filename=".launch-owner"), "pid", None) == os.getpid()
    executor._remove_unwrapped_claude_config_dir()
    assert not path.exists()


# CORAL(S116): each sweep point removes the temp dirs dead processes left, and keeps a live
# owner's
@pytest.mark.skipif(os.name == "nt", reason="the sweep needs owner uids")
@pytest.mark.parametrize("trigger", ["connect", "teardown", "close"])
async def test_each_sweep_point_removes_only_dead_owners_temp_dirs(
    monkeypatch, tmp_path, trigger
) -> None:
    """
    After a connect, a client's teardown and ``close()``, every dead owner's scratch, profile,
    seed, unwrapped config and launch dir is gone; a live owner's scratch stays.
    """
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._remove_orphaned_temp_dirs", _remove_orphaned_temp_dirs
    )
    from omnigent.native.owner_claim import create_owner_claim

    temp_root, harness_root = tmp_path / "tmp", tmp_path / "h"
    for path in (temp_root, harness_root):
        path.mkdir(mode=0o700)
    monkeypatch.setenv("TMPDIR", str(temp_root))
    monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(harness_root))
    monkeypatch.setattr(tempfile, "tempdir", None)
    # The fake transport's pid names no process of this test.
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._terminate_process_tree", lambda _process: None
    )
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    names = ("osenv-deadbeef", "seatbelt-profiles-deadbeef", "claude-seed-0123456789abcdef")
    dead = [temp_root / f"omnigent-{name}" for name in (*names, "claude-config-deadbeef")]
    dead.append(harness_root / "cdeadbeef")
    live = temp_root / "omnigent-osenv-live0000"

    def _plant() -> None:
        for path, pid in [*((path, finished.pid) for path in dead), (live, os.getpid())]:
            path.mkdir(mode=0o700)
            create_owner_claim(path, filename=".launch-owner", pid=pid)

    executor = _isolation_executor(monkeypatch, tmp_path, cli=None, isolate_claude_config=True)
    if trigger == "connect":
        _plant()
    if trigger != "close":
        events, _, _ = await _turn_with_recording_sdk(executor)
        assert any(isinstance(event, TurnComplete) for event in events), events
    if trigger == "teardown":
        _plant()
        [session_key] = executor._clients
        await executor.close_session(session_key)
    if trigger == "close":
        _plant()
        await executor.close()

    assert [path.name for path in dead if path.exists()] == []
    assert live.is_dir()
    await executor.close()


# CORAL(S116): a force close waits for every process of the CLI's tree, as the CLI can outlive
# its launcher: what outlives the 5 s bound is killed, and the sweep runs only after
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
@pytest.mark.timeout(60)
@pytest.mark.parametrize("child_stdout", ["inherited", "own-pipe"])
async def test_a_force_close_waits_for_the_whole_process_tree(monkeypatch, child_stdout) -> None:
    import contextlib
    import signal
    import time

    from omnigent.inner import _proc, claude_sdk_executor
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    ignores_term = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "print(flush=True); time.sleep(120)"
    )
    spawn = f"child = subprocess.Popen([sys.executable, '-c', {ignores_term!r}]"
    leader = {
        # The child shares the leader's stdout, so waiting on the leader also waits for it.
        "inherited": f"{spawn}); print(child.pid, flush=True)",
        # The child holds none of the leader's pipes; only the tree wait sees it.
        "own-pipe": f"{spawn}, stdout=subprocess.PIPE); child.stdout.readline(); "
        "print(child.pid, flush=True); print(flush=True)",
    }[child_stdout]
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        f"import subprocess, sys; {leader}; child.wait()",
        stdout=asyncio.subprocess.PIPE,
    )
    assert process.stdout is not None
    child = int(await process.stdout.readline())
    try:
        await process.stdout.readline()  # the child now ignores SIGTERM
        swept: list[bool] = []
        monkeypatch.setattr(
            claude_sdk_executor,
            "_remove_orphaned_temp_dirs",
            lambda: swept.append(_proc.process_alive(child)),
            raising=False,
        )
        transport = SimpleNamespace(
            _process=process,
            _stdout_stream=None,
            _stdin_stream=None,
            _stderr_stream=None,
            _stderr_task=None,
            _ready=True,
        )
        started = time.monotonic()

        await ClaudeSDKExecutor._force_close_client(
            SimpleNamespace(_query=None, _transport=transport)
        )

        assert 4.5 <= time.monotonic() - started < 30
        assert not _proc.process_alive(child), "the CLI outlived its force close"
        assert swept == [False], "the sweep ran before the tree was gone"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(child, signal.SIGKILL)


# CORAL(S116): the seed and unwrapped config claims go through the helper that refuses a link
# planted in the fresh dir
@pytest.mark.skipif(os.name == "nt", reason="POSIX links")
@pytest.mark.parametrize("site", ["seed", "unwrapped-config"])
def test_the_executors_claims_refuse_a_planted_link(monkeypatch, tmp_path, site) -> None:
    from omnigent.inner import claude_sdk_executor
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec
    from omnigent.inner.sandbox import claim_temp_dir

    outside = tmp_path / "outside"
    outside.write_text("untouched")
    planted: list[Path] = []

    def _plant_then_claim(path: Path, **kwargs) -> None:
        (path / ".launch-owner").symlink_to(outside)
        planted.append(path)
        claim_temp_dir(path, **kwargs)

    monkeypatch.setattr(claude_sdk_executor, "claim_temp_dir", _plant_then_claim)
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    if site == "seed":
        _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=True)
        spec = OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec())
        executor = _isolation_executor(
            monkeypatch, tmp_path, cli="/usr/bin/claude", os_env=spec, skills_filter="all"
        )
        executor._write_claude_config_seed()
    else:
        executor = _isolation_executor(monkeypatch, tmp_path, cli=None, isolate_claude_config=True)
        executor._claude_config_dir_for_unwrapped_cli()

    [path] = planted
    assert outside.read_text() == "untouched" and (path / ".launch-owner").is_symlink()
    executor._remove_unwrapped_claude_config_dir()
    executor._remove_claude_config_seed()


# CORAL(S116): a force close is bounded when a process outside the tree it signalled holds the
# CLI's pipe after the kill
@pytest.mark.skipif(os.name == "nt", reason="POSIX signals")
@pytest.mark.timeout(60)
async def test_a_force_close_is_bounded_when_an_escaped_process_holds_the_pipe(monkeypatch):
    import contextlib
    import signal
    import time

    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    # The leader ignores SIGTERM; a double-forked holder of its stdout escapes the snapshot.
    leader = """
import os, signal, time
signal.signal(signal.SIGTERM, signal.SIG_IGN)
read, write = os.pipe()
if os.fork() == 0:
    if os.fork() == 0:
        os.write(write, str(os.getpid()).encode())
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        time.sleep(30)
    os._exit(0)
os.wait()
os.close(write)
print(os.read(read, 32).decode(), flush=True)
time.sleep(120)
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-c", leader, stdout=asyncio.subprocess.PIPE
    )
    assert process.stdout is not None
    holder = int(await process.stdout.readline())
    try:
        transport = SimpleNamespace(
            _process=process,
            _stdout_stream=None,
            _stdin_stream=None,
            _stderr_stream=None,
            _stderr_task=None,
            _ready=True,
        )
        started = time.monotonic()

        await ClaudeSDKExecutor._force_close_client(
            SimpleNamespace(_query=None, _transport=transport)
        )

        assert time.monotonic() - started < 12, "the force close waited on the escaped holder"
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(holder, signal.SIGKILL)


# CORAL(S116): the tree wait counts a zombie as gone, so it ends at once, not at its bound
@pytest.mark.skipif(os.name == "nt", reason="POSIX zombies")
async def test_the_tree_wait_counts_a_zombie_as_gone() -> None:
    import time

    import psutil

    from omnigent.inner import _proc
    from omnigent.inner.claude_sdk_executor import _wait_for_tree
    from tests._helpers.polling import poll_until_async

    child = subprocess.Popen(
        [sys.executable, "-c", "import sys; sys.stdin.read()"], stdin=subprocess.PIPE
    )
    try:
        tree = _proc.snapshot_child_tree(child)
        assert child.pid in tree
        assert child.stdin is not None
        child.stdin.close()
        await poll_until_async(
            lambda: psutil.Process(child.pid).status() == psutil.STATUS_ZOMBIE, timeout_s=10
        )
        started = time.monotonic()
        await _wait_for_tree(SimpleNamespace(wait=AsyncMock()), tree, timeout=5)
        assert time.monotonic() - started < 2
    finally:
        child.wait()


# CORAL(S116): a connect or teardown waits briefly for its sweep, skips one while another
# runs, and close() waits for its turn
@pytest.mark.timeout(60)
async def test_a_sweep_waits_briefly_and_one_runs_at_a_time(monkeypatch, caplog) -> None:
    import time

    from omnigent.inner import claude_sdk_executor

    entered: list[int] = []
    release = threading.Event()

    def _stuck_sweep() -> None:
        entered.append(threading.get_ident())
        release.wait(20)

    monkeypatch.setattr(claude_sdk_executor, "_remove_orphaned_temp_dirs", _stuck_sweep)
    started = time.monotonic()
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        await claude_sdk_executor._sweep_orphaned_temp_dirs()
    assert time.monotonic() - started < 5 and len(entered) == 1
    assert caplog.messages == ["The temp dir sweep is still running"]

    started = time.monotonic()
    await claude_sdk_executor._sweep_orphaned_temp_dirs()
    assert time.monotonic() - started < 1 and len(entered) == 1, "a second sweep ran at once"

    closing = asyncio.create_task(claude_sdk_executor._sweep_orphaned_temp_dirs(20, wait_turn=20))
    done, _ = await asyncio.wait({closing}, timeout=0.2)
    assert not done and len(entered) == 1
    release.set()
    await closing
    assert len(entered) == 2
    background = asyncio.all_tasks() - {asyncio.current_task()}
    if background:
        await asyncio.wait(background, timeout=10)


# CORAL(S116): a cancelled caller waits for a stuck sweep only as long as its bound
@pytest.mark.timeout(60)
async def test_a_cancelled_caller_waits_for_a_stuck_sweep_only_its_bound(monkeypatch) -> None:
    from omnigent.inner import claude_sdk_executor

    started, release = threading.Event(), threading.Event()

    def _stuck_sweep() -> None:
        started.set()
        release.wait(30)

    monkeypatch.setattr(claude_sdk_executor, "_remove_orphaned_temp_dirs", _stuck_sweep)
    caller = asyncio.create_task(claude_sdk_executor._sweep_orphaned_temp_dirs(0.5))
    try:
        assert await asyncio.to_thread(started.wait, 10)
        caller.cancel()
        done, _ = await asyncio.wait({caller}, timeout=5)
        assert done, "a cancelled caller waited past its bound for a stuck sweep"
        assert caller.cancelled()
    finally:
        release.set()
        background = asyncio.all_tasks() - {asyncio.current_task()}
        if background:
            await asyncio.wait(background, timeout=10)


# CORAL(S116): the sweep scans the harness socket root only as this user's private real dir
@pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
@pytest.mark.parametrize("root", ["private", "symlink", "shared"])
def test_the_harness_root_is_swept_only_as_a_private_real_dir(monkeypatch, tmp_path, root):
    from omnigent.native.owner_claim import create_owner_claim

    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    orphan = real / "cdeadbeef"
    orphan.mkdir(mode=0o700)
    create_owner_claim(orphan, filename=".launch-owner", pid=finished.pid)
    harness_root = real
    if root == "symlink":
        harness_root = tmp_path / "link"
        harness_root.symlink_to(real)
    elif root == "shared":
        real.chmod(0o755)
    (tmp_path / "tmp").mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setenv("OMNIGENT_HARNESS_TMP_PARENT", str(harness_root))
    monkeypatch.setattr(tempfile, "tempdir", None)

    _remove_orphaned_temp_dirs()

    assert orphan.exists() is (root != "private")


# CORAL(S116): the sweep runs in a worker thread; a cancelled caller still waits for it, and a
# bounded wait returns while it goes on
@pytest.mark.timeout(60)
async def test_a_sweep_runs_off_the_event_loop_and_outlives_its_caller(monkeypatch, caplog):
    from omnigent.inner import claude_sdk_executor

    started, release = threading.Event(), threading.Event()
    threads: list[int] = []

    def _blocked_sweep() -> None:
        threads.append(threading.get_ident())
        started.set()
        release.wait(5)

    monkeypatch.setattr(claude_sdk_executor, "_remove_orphaned_temp_dirs", _blocked_sweep)
    caller = asyncio.create_task(claude_sdk_executor._sweep_orphaned_temp_dirs())
    assert await asyncio.to_thread(started.wait, 10)
    assert threads != [threading.get_ident()], "the sweep ran on the event loop's thread"
    caller.cancel()
    done, _ = await asyncio.wait({caller}, timeout=0.2)
    assert not done, "a cancelled caller left before its sweep finished"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await caller

    release.clear()
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        await claude_sdk_executor._sweep_orphaned_temp_dirs(0.05)
    assert [record.getMessage() for record in caplog.records] == [
        "The temp dir sweep is still running"
    ]
    release.set()
    # The sweep that outlived its wait finishes before the loop closes.
    background = asyncio.all_tasks() - {asyncio.current_task()}
    if background:
        await asyncio.wait(background, timeout=10)


# CORAL(S116): close() lets a client evicted on cancel finish closing before its last sweep
async def test_close_waits_for_a_cancel_eviction_before_its_last_sweep(monkeypatch, tmp_path):
    from omnigent.inner import claude_sdk_executor

    executor = _isolation_executor(monkeypatch, tmp_path, cli=None)
    order: list[str] = []
    release = asyncio.Event()

    async def _slow_teardown(_client) -> None:
        await release.wait()
        order.append("evicted")

    monkeypatch.setattr(executor, "_force_close_client", _slow_teardown)
    monkeypatch.setattr(
        claude_sdk_executor, "_remove_orphaned_temp_dirs", lambda: order.append("swept")
    )
    executor._clients["evicted"] = SimpleNamespace(client=object())
    executor._evict_client_on_cancel("evicted")
    closing = asyncio.create_task(executor.close())
    done, _ = await asyncio.wait({closing}, timeout=0.2)
    assert not done, "close() returned while a cancel eviction was still closing"
    release.set()
    await closing

    assert order == ["evicted", "swept"]


@pytest.mark.parametrize("skills", ["all", "none"], ids=["seeded", "not-seeded"])
async def test_a_seeded_mcp_server_the_host_signs_in_is_named_once(
    monkeypatch, tmp_path, caplog, claude_config_seed_source, skills
) -> None:
    """
    The host's sign-in manager keeps that server's sign-in in the host's store, which the
    sandboxed CLI's own config lacks; servers without one are not named.
    """
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    (tmp_path / "home").mkdir()
    (tmp_path / "home" / ".claude.json").write_text(json.dumps(_user_claude_config()))
    monkeypatch.setattr(
        "omnigent.inner.claude_sdk_executor._claude_mcp_auth_statuses",
        lambda: {"remote": "sign_in_required", "unseeded": "connected"},
    )
    _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=True)
    executor = _isolation_executor(
        monkeypatch,
        tmp_path,
        cli="/usr/bin/claude",
        os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec()),
        skills_filter=skills,
    )
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        for session_id in ("first", "second"):
            messages = [{"role": "user", "content": "hi", "session_id": session_id}]
            sdk = _make_recovery_fake_sdk()
            with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=sdk):
                events = [event async for event in executor.run_turn(messages, [], "")]
            assert any(isinstance(event, TurnComplete) for event in events), events
    await executor.close()

    warned = [r.getMessage() for r in caplog.records if "through this host" in r.getMessage()]
    assert len(warned) == (1 if skills == "all" else 0), warned
    assert all("'remote'" in message and "'local'" not in message for message in warned), warned


# CORAL(S115): an opted-in test may read only a config under pytest's or the system temp dir
def test_an_opted_in_test_cannot_read_a_config_outside_the_temp_dirs(
    claude_config_seed_source,
) -> None:
    from omnigent.inner.claude_sdk_executor import _claude_config_seed

    with pytest.raises(AssertionError, match="not a throwaway config"):
        _claude_config_seed({"HOME": "/nonexistent-claude-seed-home"})


@pytest.mark.parametrize(
    ("wrapped", "credential", "fix", "warns"),
    [
        (True, {}, "does not reach it", True),
        (
            True,
            {"CLAUDE_CODE_OAUTH_TOKEN": "throwaway"},
            "only with the CLAUDE_CODE_OAUTH_TOKEN",
            False,
        ),
        (True, {"ANTHROPIC_AUTH_TOKEN": "throwaway"}, "only with the ANTHROPIC_AUTH_TOKEN", False),
        (True, {"CLAUDE_CODE_USE_BEDROCK": "1"}, "does not reach it", False),
        (True, {"api_key_helper": "printf %s sk-ant-test"}, "claude auth login", False),
        (False, {}, "claude auth login", False),
    ],
    ids=["no-credential", "oauth-token", "auth-token", "bedrock", "api-key-helper", "unwrapped"],
)
async def test_a_sandboxed_cli_that_cannot_sign_in_names_the_fix(
    monkeypatch, tmp_path, caplog, wrapped, credential, fix, warns
) -> None:
    """
    Its own config holds no stored login, so the fix is an API key, a gateway or a token; a
    token already set is named instead. A CLI with no credential in sight is flagged at start,
    in words that allow for one it may still find.
    """
    from omnigent.inner.claude_sdk_executor import _CLAUDE_CREDENTIAL_ENV, CLAUDE_AUTH_FAILED_CODE
    from omnigent.inner.datamodel import OSEnvSandboxSpec, OSEnvSpec

    for name in _CLAUDE_CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    helper = credential.pop("api_key_helper", None)
    for name, value in credential.items():
        monkeypatch.setenv(name, value)
    _seed_prepare_stubs(monkeypatch, tmp_path, wrapped=wrapped)
    with caplog.at_level(logging.WARNING, logger="omnigent.inner.claude_sdk_executor"):
        executor = _isolation_executor(
            monkeypatch,
            tmp_path,
            cli="/usr/bin/claude",
            os_env=OSEnvSpec(cwd=str(tmp_path), sandbox=OSEnvSandboxSpec()),
            skills_filter="all",
            api_key_helper=helper,
        )
    flagged = [r.getMessage() for r in caplog.records if "signs in no other way" in r.getMessage()]

    error = await _only_executor_error(
        executor, _failed_result_sdk("Not logged in · Please run /login")
    )
    await executor.close()

    assert error.code == CLAUDE_AUTH_FAILED_CODE
    assert fix in (error.remediation or "") and error.remediation in error.message
    assert ("OS sandbox with its own Claude config" in error.remediation) is (
        fix != "claude auth login"
    )
    assert bool(flagged) is warns, (
        f"start warning {'missing' if warns else 'unexpected'}: {flagged}"
    )


# CORAL(S21): Coral specs check every tool call against TOOL_CALL policy from PreToolUse.


def _policy_verdict(action, reason=None):
    from omnigent.runtime.harnesses._scaffold import PolicyVerdictPayload

    return PolicyVerdictPayload(action=action, reason=reason)


def _policy_hook_executor(*, evaluator, permission_mode="bypassPermissions", hooked=True):
    executor = _default_executor(permission_mode=permission_mode, tool_call_policy_hook=hooked)
    executor._policy_evaluator = evaluator
    return executor


def _catch_all_policy_hooks(options):
    return [m for m in (options.hooks or {}).get("PreToolUse", []) if m.matcher is None]


async def _policy_gate(executor):
    (matcher,) = _catch_all_policy_hooks(await _turn_options(executor))
    (gate,) = matcher.hooks
    return gate


def _deny_output(reason):
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


@pytest.mark.parametrize(
    ("hooked", "installed"),
    [(True, True), (False, False)],
    ids=["coral", "non-coral"],
)
async def test_tool_call_policy_hook_installed_only_for_coral_sessions(hooked, installed):
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ALLOW"))
    executor = _policy_hook_executor(evaluator=evaluator, hooked=hooked)

    options = await _turn_options(executor)

    assert len(_catch_all_policy_hooks(options)) == int(installed)
    if not hooked:
        assert options.can_use_tool == executor._can_use_tool_gate


def test_tool_call_policy_hook_keeps_the_callers_hook_list():
    import claude_agent_sdk

    caller_hooks = [claude_agent_sdk.HookMatcher(matcher="Bash", hooks=[AsyncMock()])]
    options = SimpleNamespace(hooks={"PreToolUse": caller_hooks})
    executor = _policy_hook_executor(evaluator=AsyncMock())

    assert executor._install_tool_call_policy_hook(claude_agent_sdk, options) is True

    assert len(caller_hooks) == 1
    assert len(options.hooks["PreToolUse"]) == 2


@pytest.mark.parametrize("missing", ["evaluator", "hook-matcher"])
async def test_coral_spec_is_refused_when_the_policy_hook_cannot_install(missing):
    from omnigent.inner.claude_sdk_executor import CORAL_POLICY_HOOK_UNAVAILABLE_CODE

    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ALLOW"))
    executor = _policy_hook_executor(evaluator=None if missing == "evaluator" else evaluator)
    fake_sdk = _make_recovery_fake_sdk()
    if missing == "evaluator":
        from claude_agent_sdk import HookMatcher

        fake_sdk.HookMatcher = HookMatcher

    with patch("omnigent.inner.claude_sdk_executor._ensure_sdk", return_value=fake_sdk):
        events = [e async for e in executor.run_turn([{"role": "user", "content": "hi"}], [], "")]

    errors = [e for e in events if isinstance(e, ExecutorError)]
    assert [(e.code, e.retryable) for e in errors] == [(CORAL_POLICY_HOOK_UNAVAILABLE_CODE, False)]
    assert fake_sdk.created_clients == []


async def test_tool_call_policy_hook_denies_a_deny_verdict():
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_DENY", reason="no github"))
    gate = await _policy_gate(_policy_hook_executor(evaluator=evaluator))

    decision = await gate(
        {"tool_name": "mcp__github__issue_write", "tool_input": {"title": "x"}}, "tu_1", None
    )

    assert decision == _deny_output("no github")
    evaluator.assert_awaited_once_with(
        "PHASE_TOOL_CALL", {"name": "mcp__github__issue_write", "arguments": {"title": "x"}}
    )


async def test_tool_call_policy_hook_has_no_opinion_on_allow_and_omnigent_tools():
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ALLOW"))
    gate = await _policy_gate(_policy_hook_executor(evaluator=evaluator))

    assert (
        await gate({"tool_name": "mcp__omnigent__sys_os_read", "tool_input": {}}, "t", None) == {}
    )
    evaluator.assert_not_awaited()
    assert await gate({"tool_name": "ToolSearch", "tool_input": {}}, "t", None) == {}
    evaluator.assert_awaited_once()


async def test_tool_call_policy_hook_allows_an_approved_ask():
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ASK", reason="check"))
    executor = _policy_hook_executor(evaluator=evaluator)
    executor._elicitation_handler = AsyncMock(return_value=True)
    gate = await _policy_gate(executor)

    decision = await gate({"tool_name": "mcp__github__issue_write", "tool_input": {}}, "t", None)

    assert decision == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    }


async def test_tool_call_policy_hook_waits_for_a_slow_ask_approval(monkeypatch):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    async def slow_approval(tool_name, tool_input):
        await asyncio.sleep(0.05)
        return True

    monkeypatch.setattr(ClaudeSDKExecutor, "_TOOL_CALL_POLICY_DEADLINE_S", 0.01)
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ASK", reason="check"))
    executor = _policy_hook_executor(evaluator=evaluator)
    executor._elicitation_handler = slow_approval
    gate = await _policy_gate(executor)

    decision = await gate({"tool_name": "mcp__github__issue_write", "tool_input": {}}, "t", None)

    assert decision == {
        "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    }


async def test_tool_call_policy_hook_fails_closed_on_error_and_deadline(monkeypatch):
    from omnigent.inner.claude_sdk_executor import ClaudeSDKExecutor

    async def slow_verdict(phase, payload):
        await asyncio.sleep(5)

    monkeypatch.setattr(ClaudeSDKExecutor, "_TOOL_CALL_POLICY_DEADLINE_S", 0.01)
    unchecked = _deny_output("Coral could not check this tool call against policy")
    call = {"tool_name": "mcp__github__issue_write", "tool_input": {}}

    raising = await _policy_gate(
        _policy_hook_executor(evaluator=AsyncMock(side_effect=RuntimeError("server down")))
    )
    slow = await _policy_gate(_policy_hook_executor(evaluator=slow_verdict))

    assert await raising(call, "t", None) == unchecked
    assert await slow(call, "t", None) == unchecked


async def test_tool_call_policy_hook_propagates_cancellation():
    gate = await _policy_gate(
        _policy_hook_executor(evaluator=AsyncMock(side_effect=asyncio.CancelledError))
    )

    with pytest.raises(asyncio.CancelledError):
        await gate({"tool_name": "mcp__github__issue_write", "tool_input": {}}, "t", None)


async def test_tool_call_policy_hook_leaves_ask_user_question_to_its_own_hook():
    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_DENY", reason="no"))
    executor = _policy_hook_executor(evaluator=evaluator)
    executor._ask_question_handler = AsyncMock(return_value="unused")
    gate = await _policy_gate(executor)

    assert await gate({"tool_name": "AskUserQuestion", "tool_input": {}}, "t", None) == {}
    evaluator.assert_not_awaited()


async def test_tool_call_policy_hook_can_use_tool_does_not_evaluate_again():
    from claude_agent_sdk import PermissionResultAllow

    evaluator = AsyncMock(return_value=_policy_verdict("POLICY_ACTION_ALLOW"))
    executor = _policy_hook_executor(evaluator=evaluator, permission_mode="default")
    executor._elicitation_handler = AsyncMock(return_value=True)
    options = await _turn_options(executor)
    (matcher,) = _catch_all_policy_hooks(options)
    call = ("mcp__github__issue_write", {"title": "x"})
    perm_ctx = SimpleNamespace(tool_use_id="t", agent_id=None, suggestions=[])

    assert await matcher.hooks[0]({"tool_name": call[0], "tool_input": call[1]}, "t", None) == {}
    result = await options.can_use_tool(*call, perm_ctx)

    assert isinstance(result, PermissionResultAllow)
    evaluator.assert_awaited_once()
    executor._elicitation_handler.assert_awaited_once_with(*call)

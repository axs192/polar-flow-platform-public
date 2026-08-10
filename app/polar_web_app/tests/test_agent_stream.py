"""Tests for ClaudeAgent.stream()'s actual agentic loop.

Mocks only the true external boundary -- the Anthropic streaming client --
using real SDK response types (ParsedTextBlock, ToolUseBlock) for content
blocks, the same runtime shapes confirmed live during the parsed_output
investigation. Tool execution, message assembly, event yielding, and error
handling are all real code paths.
"""

import asyncio
import unittest
from unittest.mock import MagicMock, patch

import httpx
from anthropic import APIError
from anthropic.types import ThinkingBlock, ToolUseBlock, Usage
from anthropic.types.parsed_message import ParsedTextBlock
from src.agent import ClaudeAgent
from src.config import settings

# This file is about the agent loop, not S3 -- get_system_prompt() (a real S3
# read) is patched module-wide rather than per-class, matching this file's own
# "mock only the true external boundary" convention (the Anthropic client);
# context_store.get_system_prompt() gets its own real moto-backed coverage in
# test_context_store.py.
_prompt_patcher = None


def setUpModule():
    global _prompt_patcher
    _prompt_patcher = patch(
        "src.agent.context_store.get_system_prompt", return_value=settings.system_prompt
    )
    _prompt_patcher.start()


def tearDownModule():
    _prompt_patcher.stop()


def _final_message(content, stop_reason, usage=None):
    message = MagicMock()
    message.content = content
    message.stop_reason = stop_reason
    message.usage = usage if usage is not None else Usage(input_tokens=0, output_tokens=0)
    return message


class _FakeMessageStream:
    """Stands in for the async context manager `client.messages.stream()`
    returns -- ``async with ... as stream: async for t in stream.text_stream:
    ...; await stream.get_final_message()``."""

    def __init__(self, text_chunks, final_message):
        self._text_chunks = text_chunks
        self._final_message = final_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for chunk in self._text_chunks:
                yield chunk

        return _gen()

    async def get_final_message(self):
        return self._final_message


class _FakeMessagesAPI:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []  # each entry: the `messages` kwarg passed to .stream()
        self.call_kwargs = []  # each entry: every other kwarg (system, tools, thinking, ...)

    def stream(self, *, messages, **kwargs):
        self.calls.append(messages)
        self.call_kwargs.append(kwargs)
        return self._responses.pop(0)


def _run(coro_fn):
    async def _collect():
        return [event async for event in coro_fn()]

    return asyncio.run(_collect())


class StreamPlainTextTurnTestCase(unittest.TestCase):
    def test_yields_text_then_done_with_clean_serialized_content(self):
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="hello there")
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [_FakeMessageStream(["hello ", "there"], _final_message([block], "end_turn"))]
        )

        events = _run(lambda: agent.stream("hi"))

        self.assertEqual(events[0], {"type": "text", "text": "hello "})
        self.assertEqual(events[1], {"type": "text", "text": "there"})
        done = events[-1]
        self.assertEqual(done["type"], "done")
        assistant_content = done["new_messages"][-1]["content"]
        # Regression check for the real parsed_output 400: the serialized
        # block must not carry response-only fields back out as request input.
        self.assertNotIn("parsed_output", assistant_content[0])
        self.assertEqual(assistant_content[0]["text"], "hello there")

    def test_history_tail_gets_a_cache_breakpoint_on_replay(self):
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api
        history = [
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": [{"type": "text", "text": "earlier answer"}]},
        ]

        _run(lambda: agent.stream("follow-up", history=history))

        sent_messages = fake_api.calls[0]
        self.assertEqual(sent_messages[1]["content"][0]["cache_control"], {"type": "ephemeral"})
        # The caller's own history list/dicts must not be mutated in place.
        self.assertNotIn("cache_control", history[1]["content"][0])

    def test_extra_system_is_appended_to_the_base_system_prompt(self):
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api

        _run(lambda: agent.stream("hi", extra_system="Athlete profile: marathon runner."))

        system_text = fake_api.call_kwargs[0]["system"][0]["text"]
        self.assertIn(settings.system_prompt, system_text)
        self.assertIn("Athlete profile: marathon runner.", system_text)

    def test_thinking_param_included_when_enabled(self):
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api
        original = settings.enable_thinking
        settings.enable_thinking = True
        try:
            _run(lambda: agent.stream("hi"))
        finally:
            settings.enable_thinking = original

        self.assertEqual(fake_api.call_kwargs[0]["thinking"], {"type": "adaptive"})

    def test_temperature_is_never_sent(self):
        # Regression test: Claude Sonnet 5 (and virtually every current-generation
        # model) returns a real 400 -- "temperature is deprecated for this model" --
        # on any non-default temperature/top_p/top_k. Confirmed live in production.
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api

        _run(lambda: agent.stream("hi"))

        self.assertNotIn("temperature", fake_api.call_kwargs[0])
        self.assertNotIn("top_p", fake_api.call_kwargs[0])
        self.assertNotIn("top_k", fake_api.call_kwargs[0])

    def test_system_prompt_comes_from_context_store_not_the_static_config(self):
        # Regression check for the S3-relocation wiring: stream() must call
        # context_store.get_system_prompt() (hot-editable in S3) rather than
        # reading self.config.system_prompt directly, or an S3-edited prompt
        # would never actually reach the model.
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api

        with patch(
            "src.agent.context_store.get_system_prompt", return_value="Custom S3 prompt text"
        ):
            _run(lambda: agent.stream("hi"))

        system_text = fake_api.call_kwargs[0]["system"][0]["text"]
        self.assertIn("Custom S3 prompt text", system_text)
        self.assertNotIn(settings.system_prompt, system_text)

    def test_base_system_overrides_the_coach_prompt_entirely(self):
        # The plan-building agent passes its own persona via base_system --
        # it must replace context_store.get_system_prompt(), not append to it.
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api

        _run(lambda: agent.stream("hi", base_system="Plan-building persona text."))

        system_text = fake_api.call_kwargs[0]["system"][0]["text"]
        self.assertIn("Plan-building persona text.", system_text)
        self.assertNotIn(settings.system_prompt, system_text)

    def test_omitting_base_system_is_identical_to_before_it_existed(self):
        # Regression guard for the existing coach path: adding the base_system
        # param must not change behaviour when a caller (like /ask) never
        # passes it.
        agent = ClaudeAgent(settings)
        block = ParsedTextBlock(type="text", text="ok")
        agent.client = MagicMock()
        fake_api = _FakeMessagesAPI([_FakeMessageStream(["ok"], _final_message([block], "end_turn"))])
        agent.client.messages = fake_api

        _run(lambda: agent.stream("hi"))

        system_text = fake_api.call_kwargs[0]["system"][0]["text"]
        self.assertEqual(system_text, settings.system_prompt)


class StreamToolUseTurnTestCase(unittest.TestCase):
    def test_runs_the_tool_and_continues_to_a_final_answer(self):
        agent = ClaudeAgent(settings)
        tool_block = ToolUseBlock(type="tool_use", id="toolu_1", name="get_my_training_data", input={})
        text_block = ParsedTextBlock(type="text", text="your load looks good")
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [
                _FakeMessageStream([], _final_message([tool_block], "tool_use")),
                _FakeMessageStream(["your load looks good"], _final_message([text_block], "end_turn")),
            ]
        )

        with patch("src.agent.run_tool", return_value={"training_load": {"7d": 5}}) as mock_run_tool:
            events = _run(lambda: agent.stream("how's my training?"))

        mock_run_tool.assert_called_once_with("get_my_training_data", {})
        tool_events = [e for e in events if e["type"] == "tool"]
        self.assertEqual(tool_events, [{"type": "tool", "name": "get_my_training_data", "input": {}}])

        done = events[-1]
        new_messages = done["new_messages"]
        # user question, assistant tool_use turn, tool_result turn, final assistant turn
        self.assertEqual(len(new_messages), 4)
        self.assertEqual(new_messages[2]["content"][0]["type"], "tool_result")
        self.assertEqual(new_messages[2]["content"][0]["tool_use_id"], "toolu_1")
        self.assertEqual(new_messages[3]["content"][0]["text"], "your load looks good")

    def test_non_cacheable_tool_result_is_sent_as_plain_text(self):
        agent = ClaudeAgent(settings)
        tool_block = ToolUseBlock(
            type="tool_use", id="toolu_2", name="save_athlete_profile", input={"sport": "running"}
        )
        text_block = ParsedTextBlock(type="text", text="saved it")
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [
                _FakeMessageStream([], _final_message([tool_block], "tool_use")),
                _FakeMessageStream(["saved it"], _final_message([text_block], "end_turn")),
            ]
        )

        with patch("src.agent.run_tool", return_value={"sport": "running"}):
            events = _run(lambda: agent.stream("my sport is running"))

        done = events[-1]
        tool_result_content = done["new_messages"][2]["content"][0]["content"]
        # Plain JSON string, not a cache_control-wrapped block list -- only
        # get_my_training_data's result is large enough to be worth caching.
        self.assertIsInstance(tool_result_content, str)
        self.assertIn("running", tool_result_content)

    def test_non_tool_use_blocks_alongside_a_tool_call_are_skipped(self):
        # A real shape with adaptive thinking on: the model can emit a
        # thinking block and a tool_use block in the same turn.
        agent = ClaudeAgent(settings)
        thinking_block = ThinkingBlock(type="thinking", thinking="reasoning...", signature="sig123")
        tool_block = ToolUseBlock(type="tool_use", id="toolu_3", name="get_my_training_data", input={})
        text_block = ParsedTextBlock(type="text", text="done")
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [
                _FakeMessageStream([], _final_message([thinking_block, tool_block], "tool_use")),
                _FakeMessageStream(["done"], _final_message([text_block], "end_turn")),
            ]
        )

        with patch("src.agent.run_tool", return_value={}) as mock_run_tool:
            events = _run(lambda: agent.stream("how's my training?"))

        mock_run_tool.assert_called_once_with("get_my_training_data", {})
        tool_events = [e for e in events if e["type"] == "tool"]
        self.assertEqual(len(tool_events), 1)

    def test_usage_is_summed_across_tool_loop_iterations_not_just_the_last(self):
        agent = ClaudeAgent(settings)
        tool_block = ToolUseBlock(type="tool_use", id="toolu_5", name="get_my_training_data", input={})
        text_block = ParsedTextBlock(type="text", text="your load looks good")
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [
                _FakeMessageStream(
                    [],
                    _final_message(
                        [tool_block],
                        "tool_use",
                        usage=Usage(
                            input_tokens=100,
                            output_tokens=10,
                            cache_read_input_tokens=5,
                            cache_creation_input_tokens=0,
                        ),
                    ),
                ),
                _FakeMessageStream(
                    ["your load looks good"],
                    _final_message(
                        [text_block],
                        "end_turn",
                        usage=Usage(input_tokens=200, output_tokens=30),
                    ),
                ),
            ]
        )

        with patch("src.agent.run_tool", return_value={"training_load": {"7d": 5}}):
            events = _run(lambda: agent.stream("how's my training?"))

        done = events[-1]
        self.assertEqual(
            done["usage"],
            {
                "input_tokens": 300,
                "output_tokens": 40,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 5,
            },
        )


class StreamErrorHandlingTestCase(unittest.TestCase):
    def test_api_error_yields_a_clean_error_event(self):
        agent = ClaudeAgent(settings)
        agent.client = MagicMock()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        error = APIError("boom", request, body=None)
        agent.client.messages = MagicMock()
        agent.client.messages.stream = MagicMock(side_effect=error)

        events = _run(lambda: agent.stream("hi"))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "error")
        self.assertIn("Anthropic API error", events[0]["message"])

    def test_unexpected_error_yields_a_generic_error_event(self):
        # A non-API failure (e.g. a bug in a tool) shouldn't crash the
        # generator -- it should surface as a clean error event too.
        agent = ClaudeAgent(settings)
        tool_block = ToolUseBlock(type="tool_use", id="toolu_4", name="get_my_training_data", input={})
        agent.client = MagicMock()
        agent.client.messages = _FakeMessagesAPI(
            [_FakeMessageStream([], _final_message([tool_block], "tool_use"))]
        )

        with patch("src.agent.run_tool", side_effect=ValueError("boom")):
            events = _run(lambda: agent.stream("how's my training?"))

        error_events = [e for e in events if e["type"] == "error"]
        self.assertEqual(len(error_events), 1)
        self.assertEqual(error_events[0]["message"], "boom")


if __name__ == "__main__":
    unittest.main()

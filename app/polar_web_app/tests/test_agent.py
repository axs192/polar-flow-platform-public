import unittest

from anthropic.types import ToolUseBlock
from anthropic.types.parsed_message import ParsedTextBlock
from src.agent import _dump_response_block, _with_cache_breakpoint


class WithCacheBreakpointTestCase(unittest.TestCase):
    def test_marks_only_the_last_block_of_list_content(self):
        message = {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "first"},
                {"type": "text", "text": "second"},
            ],
        }

        result = _with_cache_breakpoint(message)

        self.assertNotIn("cache_control", result["content"][0])
        self.assertEqual(result["content"][1]["cache_control"], {"type": "ephemeral"})
        self.assertEqual(result["content"][1]["text"], "second")

    def test_does_not_mutate_the_original_message(self):
        message = {"role": "assistant", "content": [{"type": "text", "text": "hi"}]}

        _with_cache_breakpoint(message)

        self.assertNotIn("cache_control", message["content"][0])

    def test_string_content_is_a_no_op(self):
        message = {"role": "user", "content": "plain question"}

        result = _with_cache_breakpoint(message)

        self.assertEqual(result, message)

    def test_empty_content_list_is_a_no_op(self):
        message = {"role": "assistant", "content": []}

        result = _with_cache_breakpoint(message)

        self.assertEqual(result, message)


class DumpResponseBlockTestCase(unittest.TestCase):
    def test_drops_unset_response_only_fields(self):
        # Regression test for a real production 400. `client.messages.stream()`
        # actually returns `ParsedTextBlock` (a `TextBlock` subclass), not
        # plain `TextBlock` -- confirmed live, since the plain base class
        # doesn't carry the extra field and wouldn't reproduce the bug. It
        # adds `parsed_output` (unset/None here, since this app never
        # requests structured output), which isn't valid on request input.
        # Re-sending it verbatim as replayed history broke every second turn.
        block = ParsedTextBlock(type="text", text="hello")

        result = _dump_response_block(block)

        self.assertEqual(result, {"type": "text", "text": "hello"})
        self.assertNotIn("parsed_output", result)
        self.assertNotIn("citations", result)

    def test_keeps_real_fields_on_a_tool_use_block(self):
        block = ToolUseBlock(type="tool_use", id="toolu_1", name="get_my_training_data", input={})

        result = _dump_response_block(block)

        self.assertEqual(result["type"], "tool_use")
        self.assertEqual(result["id"], "toolu_1")
        self.assertEqual(result["name"], "get_my_training_data")
        self.assertEqual(result["input"], {})


if __name__ == "__main__":
    unittest.main()

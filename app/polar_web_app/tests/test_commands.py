import unittest
from unittest.mock import patch

import boto3
from moto import mock_aws
from src import commands, context_store
from src.config import settings


class CommandsTestCase(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        settings.context_bucket = "test-context-bucket"
        settings.polar_user_id = "polar-user-1"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=settings.context_bucket)
        context_store._s3_client = None

    def tearDown(self):
        context_store._s3_client = None
        self.mock_aws.stop()


class TestIsCommand(unittest.TestCase):
    def test_slash_prefixed_text_is_a_command(self):
        self.assertTrue(commands.is_command("/profile"))
        self.assertTrue(commands.is_command("  /help  "))

    def test_plain_text_is_not_a_command(self):
        self.assertFalse(commands.is_command("how was my week?"))


class TestProfileCommand(CommandsTestCase):
    def test_no_profile_saved_yet(self):
        outcome = commands.handle_command("/profile", "user-1")

        self.assertIn("don't have a coaching profile", outcome.direct_reply)
        self.assertIsNone(outcome.extra_system)

    def test_formats_existing_profile(self):
        context_store.save_profile("user-1", sport="running", goal="75km ultra")

        outcome = commands.handle_command("/profile", "user-1")

        self.assertIn("running", outcome.direct_reply)
        self.assertIn("75km ultra", outcome.direct_reply)

    def test_includes_communication_style_when_set(self):
        context_store.save_profile(
            "user-1", sport="running", goal="75km ultra", communication_style="brief and blunt"
        )

        outcome = commands.handle_command("/profile", "user-1")

        self.assertIn("Communication style", outcome.direct_reply)
        self.assertIn("brief and blunt", outcome.direct_reply)


class TestHelpCommand(CommandsTestCase):
    def test_lists_all_commands(self):
        outcome = commands.handle_command("/help", "user-1")

        for name in commands.COMMANDS:
            self.assertIn(name, outcome.direct_reply)


class TestRefreshDataCommand(CommandsTestCase):
    @patch("exercise_insights.core.get_exercise_metrics")
    def test_forces_a_fresh_fetch(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 5}}

        outcome = commands.handle_command("/refresh-data", "user-1")

        mock_get_metrics.assert_called_once()
        self.assertIn("refreshed", outcome.direct_reply.lower())
        self.assertEqual(
            context_store.get_cached_training_data("user-1"), {"training_load": {"7d": 5}}
        )

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_marks_refresh_pending_so_the_next_turn_re_fetches(self, mock_get_metrics):
        # /refresh-data replies directly (no LLM call), so this exchange
        # never reaches the agent's conversation history -- the flag is what
        # tells the *next* real turn to call get_my_training_data again
        # instead of silently reusing stale in-context values.
        mock_get_metrics.return_value = {"training_load": {"7d": 5}}

        commands.handle_command("/refresh-data", "user-1")

        self.assertTrue(context_store.consume_refresh_pending("user-1"))


class TestResetHistoryCommand(CommandsTestCase):
    def test_clears_messages_but_keeps_training_data(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "hi"}])
        context_store.save_training_data("user-1", {"training_load": {"7d": 5}})

        outcome = commands.handle_command("/reset-history", "user-1")

        self.assertIn("cleared", outcome.direct_reply.lower())
        self.assertEqual(context_store.get_history("user-1")["messages"], [])
        self.assertEqual(
            context_store.get_cached_training_data("user-1"), {"training_load": {"7d": 5}}
        )


class TestUsageCommand(CommandsTestCase):
    def test_no_usage_recorded_yet(self):
        outcome = commands.handle_command("/usage", "user-1")

        self.assertIn("No usage recorded yet", outcome.direct_reply)

    def test_reflects_recorded_usage(self):
        context_store.record_usage("user-1", {"input_tokens": 100, "output_tokens": 20})

        outcome = commands.handle_command("/usage", "user-1")

        self.assertIn("Today", outcome.direct_reply)
        self.assertIn("This month", outcome.direct_reply)
        self.assertIn("100", outcome.direct_reply)
        self.assertIn("20", outcome.direct_reply)


class TestUpdateProfileCommand(CommandsTestCase):
    def test_falls_through_to_agent_with_instruction(self):
        outcome = commands.handle_command("/update-profile", "user-1")

        self.assertIsNone(outcome.direct_reply)
        self.assertIn("update-profile", outcome.extra_system)

    def test_instruction_includes_existing_profile(self):
        context_store.save_profile("user-1", sport="running", goal="75km ultra")

        outcome = commands.handle_command("/update-profile", "user-1")

        self.assertIn("75km ultra", outcome.extra_system)


class TestUnknownCommand(CommandsTestCase):
    def test_unknown_command_gets_a_helpful_reply(self):
        outcome = commands.handle_command("/nonexistent", "user-1")

        self.assertIn("Unknown command", outcome.direct_reply)


if __name__ == "__main__":
    unittest.main()

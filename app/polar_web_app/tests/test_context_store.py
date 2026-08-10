import unittest
from datetime import UTC, date, datetime, timedelta

import boto3
from moto import mock_aws
from src import context_store
from src.config import settings


class ContextStoreTestCase(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        settings.context_bucket = "test-context-bucket"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=settings.context_bucket)
        # The module caches its own boto3 client; drop it so a fresh one binds
        # inside the active moto mock.
        context_store._s3_client = None

    def tearDown(self):
        context_store._s3_client = None
        self.mock_aws.stop()


class TestProfile(ContextStoreTestCase):
    def test_get_profile_returns_none_when_unset(self):
        self.assertIsNone(context_store.get_profile("user-1"))

    def test_save_then_get_profile_round_trips(self):
        context_store.save_profile("user-1", sport="running", goal="75km ultra")

        profile = context_store.get_profile("user-1")

        self.assertEqual(profile["sport"], "running")
        self.assertEqual(profile["goal"], "75km ultra")
        self.assertIn("updated_at", profile)

    def test_save_profile_is_scoped_per_user(self):
        context_store.save_profile("user-1", sport="running")
        context_store.save_profile("user-2", sport="cycling")

        self.assertEqual(context_store.get_profile("user-1")["sport"], "running")
        self.assertEqual(context_store.get_profile("user-2")["sport"], "cycling")


class TestPlan(ContextStoreTestCase):
    def test_get_plan_returns_none_when_unset(self):
        self.assertIsNone(context_store.get_plan("user-1"))

    def test_save_then_get_plan_round_trips(self):
        context_store.save_plan(
            "user-1",
            start_date="2026-08-10",
            weeks=[{"planned_distance_miles": 40.0, "planned_duration_hr": 5.5, "planned_elevation_gain_ft": 2000}],
            themes=[{"label": "Base building", "weeks": [0], "color": "#3987e5"}],
        )

        plan = context_store.get_plan("user-1")

        self.assertEqual(plan["start_date"], "2026-08-10")
        self.assertEqual(len(plan["weeks"]), 1)
        self.assertEqual(plan["themes"][0]["label"], "Base building")
        self.assertIn("updated_at", plan)

    def test_save_plan_is_scoped_per_user(self):
        context_store.save_plan("user-1", start_date="2026-08-10", weeks=[], themes=[])
        context_store.save_plan("user-2", start_date="2026-09-01", weeks=[], themes=[])

        self.assertEqual(context_store.get_plan("user-1")["start_date"], "2026-08-10")
        self.assertEqual(context_store.get_plan("user-2")["start_date"], "2026-09-01")

    def test_save_plan_upsert_overwrites_previous_plan(self):
        context_store.save_plan("user-1", start_date="2026-08-10", weeks=[], themes=[])

        context_store.save_plan("user-1", start_date="2026-09-01", weeks=[], themes=[])

        self.assertEqual(context_store.get_plan("user-1")["start_date"], "2026-09-01")


class TestConversationHistory(ContextStoreTestCase):
    def test_get_history_returns_empty_shell_for_new_user(self):
        history = context_store.get_history("user-1")

        self.assertEqual(history["messages"], [])
        self.assertIsNone(history["training_data"])

    def test_append_messages_persists_across_calls(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "hi"}])
        context_store.append_messages("user-1", [{"role": "assistant", "content": "hello"}])

        messages = context_store.get_history("user-1")["messages"]

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "hi")
        self.assertEqual(messages[1]["content"], "hello")

    def test_clear_history_empties_messages_but_keeps_training_data(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "hi"}])
        context_store.save_training_data("user-1", {"training_load": {"7d": 10}})

        context_store.clear_history("user-1")

        history = context_store.get_history("user-1")
        self.assertEqual(history["messages"], [])
        self.assertEqual(history["training_data"], {"training_load": {"7d": 10}})


class TestConversationHistoryKinds(ContextStoreTestCase):
    # The plan-building chat gets its own separate transcript (kind=
    # "plan_conversation") from the coach chat's default "conversation" --
    # genuinely separate chat surfaces, not one interleaved history.

    def test_default_kind_and_plan_conversation_kind_are_independent(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "coach hi"}])
        context_store.append_messages("user-1", [{"role": "user", "content": "plan hi"}], kind="plan_conversation")

        coach_history = context_store.get_history("user-1")
        plan_history = context_store.get_history("user-1", kind="plan_conversation")

        self.assertEqual(coach_history["messages"][0]["content"], "coach hi")
        self.assertEqual(plan_history["messages"][0]["content"], "plan hi")

    def test_clear_history_is_scoped_by_kind(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "coach"}])
        context_store.append_messages("user-1", [{"role": "user", "content": "plan"}], kind="plan_conversation")

        context_store.clear_history("user-1", kind="plan_conversation")

        self.assertEqual(context_store.get_history("user-1")["messages"][0]["content"], "coach")
        self.assertEqual(context_store.get_history("user-1", kind="plan_conversation")["messages"], [])


class TestTrainingDataCache(ContextStoreTestCase):
    def test_no_cached_data_returns_none(self):
        self.assertIsNone(context_store.get_cached_training_data("user-1"))

    def test_data_fetched_today_is_reused(self):
        context_store.save_training_data("user-1", {"training_load": {"7d": 10}})

        cached = context_store.get_cached_training_data("user-1")

        self.assertEqual(cached, {"training_load": {"7d": 10}})

    def test_stale_data_from_a_previous_day_is_not_reused(self):
        context_store.save_training_data("user-1", {"training_load": {"7d": 10}})
        stale_history = context_store.get_history("user-1")
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        stale_history["training_data_fetched_at"] = yesterday
        context_store._put_json(context_store._conversation_key("user-1"), stale_history)

        self.assertIsNone(context_store.get_cached_training_data("user-1"))


class TestUsage(ContextStoreTestCase):
    def test_no_usage_recorded_returns_zero_shape(self):
        summary = context_store.get_usage_summary("user-1")

        self.assertEqual(summary["today"]["requests"], 0)
        self.assertEqual(summary["month_to_date"]["input_tokens"], 0)

    def test_record_usage_accumulates_across_calls_same_day(self):
        context_store.record_usage("user-1", {"input_tokens": 100, "output_tokens": 20})
        context_store.record_usage("user-1", {"input_tokens": 50, "output_tokens": 10})

        summary = context_store.get_usage_summary("user-1")

        self.assertEqual(summary["today"]["requests"], 2)
        self.assertEqual(summary["today"]["input_tokens"], 150)
        self.assertEqual(summary["today"]["output_tokens"], 30)

    def test_usage_is_scoped_per_user(self):
        context_store.record_usage("user-1", {"input_tokens": 100, "output_tokens": 20})
        context_store.record_usage("user-2", {"input_tokens": 5, "output_tokens": 1})

        self.assertEqual(context_store.get_usage_summary("user-1")["today"]["input_tokens"], 100)
        self.assertEqual(context_store.get_usage_summary("user-2")["today"]["input_tokens"], 5)

    def test_missing_counter_fields_default_to_zero(self):
        # A tool-only turn or an early error can plausibly carry a partial
        # usage dict -- record_usage must not KeyError on a missing field.
        context_store.record_usage("user-1", {"input_tokens": 10})

        summary = context_store.get_usage_summary("user-1")

        self.assertEqual(summary["today"]["input_tokens"], 10)
        self.assertEqual(summary["today"]["output_tokens"], 0)

    def test_a_prior_day_this_month_counts_toward_month_to_date_not_today(self):
        context_store.record_usage("user-1", {"input_tokens": 100, "output_tokens": 20})
        data = context_store._get_json(context_store._usage_key("user-1"))
        # A day in the current month guaranteed distinct from today, however
        # today falls -- avoids colliding with today's own bucket.
        today = date.today()
        other_day = 15 if today.day != 15 else 16
        other_day_this_month = today.replace(day=other_day).isoformat()
        data["days"][other_day_this_month] = {
            "requests": 1,
            "input_tokens": 40,
            "output_tokens": 5,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        context_store._put_json(context_store._usage_key("user-1"), data)

        summary = context_store.get_usage_summary("user-1")

        self.assertEqual(summary["today"]["input_tokens"], 100)
        self.assertEqual(summary["month_to_date"]["input_tokens"], 140)

    def test_a_prior_month_does_not_count_toward_month_to_date(self):
        context_store.record_usage("user-1", {"input_tokens": 100, "output_tokens": 20})
        data = context_store._get_json(context_store._usage_key("user-1"))
        last_year = date.today().replace(year=date.today().year - 1).isoformat()
        data["days"][last_year] = {
            "requests": 1,
            "input_tokens": 999,
            "output_tokens": 999,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
        context_store._put_json(context_store._usage_key("user-1"), data)

        summary = context_store.get_usage_summary("user-1")

        self.assertEqual(summary["month_to_date"]["input_tokens"], 100)


class TestRefreshPending(ContextStoreTestCase):
    def test_starts_false_for_a_fresh_user(self):
        self.assertFalse(context_store.consume_refresh_pending("user-1"))

    def test_mark_then_consume_returns_true_once(self):
        context_store.mark_refresh_pending("user-1")

        self.assertTrue(context_store.consume_refresh_pending("user-1"))
        # One-shot: the very next check (no new /refresh-data in between)
        # must not still report pending, or every subsequent turn would
        # keep telling the agent to re-fetch forever.
        self.assertFalse(context_store.consume_refresh_pending("user-1"))

    def test_scoped_per_user(self):
        context_store.mark_refresh_pending("user-1")

        self.assertFalse(context_store.consume_refresh_pending("user-2"))
        self.assertTrue(context_store.consume_refresh_pending("user-1"))

    def test_does_not_disturb_existing_messages_or_training_data(self):
        context_store.append_messages("user-1", [{"role": "user", "content": "hi"}])
        context_store.save_training_data("user-1", {"training_load": {"7d": 10}})

        context_store.mark_refresh_pending("user-1")

        history = context_store.get_history("user-1")
        self.assertEqual(len(history["messages"]), 1)
        self.assertEqual(history["training_data"], {"training_load": {"7d": 10}})


class TestHistoryWindowing(ContextStoreTestCase):
    # Real observation this fixes: a real conversation's prompt cache reached
    # ~100k tokens because append_messages never trimmed. window=3 here (not
    # the real default of 10) purely to keep these tests small and fast.

    def setUp(self):
        super().setUp()
        self._original_max_turns = settings.max_history_turns
        settings.max_history_turns = 3

    def tearDown(self):
        settings.max_history_turns = self._original_max_turns
        super().tearDown()

    def _turn(self, label):
        return [{"role": "user", "content": f"q{label}"}, {"role": "assistant", "content": f"a{label}"}]

    def test_keeps_only_the_last_n_turns(self):
        for i in range(5):
            context_store.append_messages("user-1", self._turn(i))

        history = context_store.get_history("user-1")

        self.assertEqual(len(history["messages"]), 6)  # 3 turns x 2 messages
        contents = [m["content"] for m in history["messages"]]
        self.assertEqual(contents, ["q2", "a2", "q3", "a3", "q4", "a4"])
        self.assertEqual(history["turn_lengths"], [2, 2, 2])

    def test_tool_use_turn_within_the_window_is_kept_whole(self):
        tool_turn = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "x", "input": {}}]},
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "r"}]},
            {"role": "assistant", "content": "final"},
        ]
        context_store.append_messages("user-1", self._turn("a"))
        context_store.append_messages("user-1", tool_turn)

        history = context_store.get_history("user-1")

        # 2 turns total, well within window=3 -- the tool turn's 4 messages
        # come back as a contiguous, complete block, never split mid-turn.
        self.assertEqual(history["messages"][-4:], tool_turn)

    def test_legacy_data_without_turn_lengths_trims_to_the_new_turn_only(self):
        # Pre-migration stored data: a big legacy messages list with no
        # turn_lengths key at all -- the first append after this ships must
        # not KeyError, and should trim down to just the newest turn (a
        # one-time reset of the old backlog, not a gradual rolloff).
        legacy = context_store.get_history("user-1")
        legacy["messages"] = [{"role": "user", "content": "old"}] * 20
        del legacy["turn_lengths"]
        context_store._put_json(context_store._conversation_key("user-1"), legacy)

        context_store.append_messages("user-1", self._turn("new"))

        history = context_store.get_history("user-1")
        self.assertEqual(history["messages"], self._turn("new"))

    def test_clear_history_resets_turn_lengths_too(self):
        context_store.append_messages("user-1", self._turn(1))

        context_store.clear_history("user-1")
        context_store.append_messages("user-1", self._turn(2))

        history = context_store.get_history("user-1")
        self.assertEqual(history["turn_lengths"], [2])


class TestSystemPrompt(ContextStoreTestCase):
    def test_falls_back_to_settings_when_object_does_not_exist(self):
        self.assertEqual(context_store.get_system_prompt(), settings.system_prompt)

    def test_returns_s3_content_when_present(self):
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=settings.context_bucket, Key="system_prompt.txt", Body=b"Custom prompt text"
        )

        self.assertEqual(context_store.get_system_prompt(), "Custom prompt text")


class TestPlanSystemPrompt(ContextStoreTestCase):
    def test_falls_back_to_settings_when_object_does_not_exist(self):
        self.assertEqual(context_store.get_plan_system_prompt(), settings.plan_system_prompt)

    def test_returns_s3_content_when_present(self):
        boto3.client("s3", region_name="us-east-1").put_object(
            Bucket=settings.context_bucket, Key="plan_system_prompt.txt", Body=b"Custom plan prompt text"
        )

        self.assertEqual(context_store.get_plan_system_prompt(), "Custom plan prompt text")


if __name__ == "__main__":
    unittest.main()

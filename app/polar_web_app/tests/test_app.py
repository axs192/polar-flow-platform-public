"""Tests for the FastAPI HTTP layer (app.py).

Mocks only the two true external boundaries -- the Anthropic API (via a fake
Agent that records what it was called with) and Supabase (only for the
login-flow tests that specifically exercise it). Everything else -- routing,
session-cookie auth, slash-command interception, profile-aware system-prompt
selection, SSE persistence -- runs for real, the same "mock the boundary, not
the logic" pattern this repo already uses for AWS (moto) and HTTP
(responses/respx) elsewhere.
"""

import unittest
from unittest.mock import MagicMock, patch

import boto3
import src.app as app_module
from fastapi.testclient import TestClient
from moto import mock_aws
from src import commands, context_store
from src.agent import Agent
from src.config import settings
from supabase_auth.errors import AuthApiError


class _RecordingAgent(Agent):
    """Stands in for ClaudeAgent: records each call's args, yields canned
    events. Stubs the LLM call itself, nothing else in the request path."""

    def __init__(self):
        self.calls = []

    async def stream(self, question, *, history=None, extra_system=None, base_system=None):
        self.calls.append(
            {
                "question": question,
                "history": history,
                "extra_system": extra_system,
                "base_system": base_system,
            }
        )
        yield {"type": "text", "text": "canned answer"}
        yield {
            "type": "done",
            "new_messages": [
                {"role": "user", "content": question},
                {"role": "assistant", "content": [{"type": "text", "text": "canned answer"}]},
            ],
            "usage": {
                "input_tokens": 100,
                "output_tokens": 20,
                "cache_creation_input_tokens": 0,
                "cache_read_input_tokens": 0,
            },
        }


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.mock_aws = mock_aws()
        self.mock_aws.start()
        settings.context_bucket = "test-context-bucket"
        settings.polar_user_id = "polar-user-1"
        settings.supabase_url = "https://example.supabase.co"
        settings.supabase_key = "test-key"
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=settings.context_bucket)
        context_store._s3_client = None

        self.recording_agent = _RecordingAgent()
        self._agent_patch = patch.object(app_module, "agent", self.recording_agent)
        self._agent_patch.start()

        self.client = TestClient(app_module.app)

        # A pre-authenticated session, injected directly into the real
        # session store -- exercises the real cookie -> session lookup path
        # (_lookup_session/optional_user/require_user) without re-mocking
        # Supabase in every single test.
        self.user_id = "user-1"
        self.session_id = "test-session-id"
        app_module._sessions[self.session_id] = app_module._Session(
            user=app_module.AuthUser(id=self.user_id, email="athlete@example.com"),
            access_token="tok",
            refresh_token="refresh",
            expires_at=None,
        )
        self.client.cookies.set(settings.auth_cookie_name, self.session_id)

    def tearDown(self):
        self._agent_patch.stop()
        app_module._sessions.clear()
        context_store._s3_client = None
        self.mock_aws.stop()


class TestAuthGating(AppTestCase):
    def test_index_redirects_when_unauthenticated(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.get("/", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_index_serves_chat_page_when_authenticated(self):
        resp = self.client.get("/")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"AI Running Coach", resp.content)

    def test_ask_requires_auth(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.post("/ask", json={"question": "hi"})

        self.assertEqual(resp.status_code, 401)

    def test_config_requires_auth(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.get("/config")

        self.assertEqual(resp.status_code, 401)

    def test_login_page_redirects_when_already_authenticated(self):
        resp = self.client.get("/login", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")


class TestConfigEndpoint(AppTestCase):
    def test_returns_app_title(self):
        resp = self.client.get("/config")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["title"], settings.app_title)

    def test_returns_the_same_commands_help_reads_from(self):
        resp = self.client.get("/config")

        self.assertEqual(resp.json()["commands"], commands.COMMANDS)


class TestStaticAssetCaching(AppTestCase):
    def test_static_files_are_never_cached(self):
        resp = self.client.get("/static/app.js")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["cache-control"], "no-store")

    def test_non_static_routes_are_unaffected(self):
        resp = self.client.get("/config")

        self.assertNotIn("cache-control", {k.lower() for k in resp.headers})


class TestGreetingEndpoint(AppTestCase):
    def test_no_profile_invites_onboarding(self):
        resp = self.client.get("/greeting")

        self.assertEqual(resp.status_code, 200)
        self.assertIn("don't have your athlete profile", resp.json()["text"])

    def test_existing_profile_is_summarized(self):
        context_store.save_profile(self.user_id, sport="running", goal="75km ultra")

        resp = self.client.get("/greeting")

        text = resp.json()["text"]
        self.assertIn("Welcome back", text)
        self.assertIn("running", text)
        self.assertIn("75km ultra", text)


class TestAskRouting(AppTestCase):
    def test_plain_question_reaches_the_agent(self):
        resp = self.client.post("/ask", json={"question": "how was my week?"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.recording_agent.calls), 1)
        self.assertEqual(self.recording_agent.calls[0]["question"], "how was my week?")

    def test_no_profile_injects_onboarding_instruction(self):
        self.client.post("/ask", json={"question": "hi"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("no coaching profile saved yet", extra_system)

    def test_existing_profile_is_injected_as_context(self):
        context_store.save_profile(self.user_id, sport="running", goal="75km ultra")

        self.client.post("/ask", json={"question": "how's it going?"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("75km ultra", extra_system)

    def test_slash_command_never_reaches_the_agent(self):
        resp = self.client.post("/ask", json={"question": "/profile"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.recording_agent.calls, [])
        self.assertIn(b"coaching profile", resp.content)

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_question_right_after_refresh_data_is_told_to_re_fetch(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 5}}
        self.client.post("/ask", json={"question": "/refresh-data"})

        self.client.post("/ask", json={"question": "how's my training now?"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("force-refreshed", extra_system)

    @patch("exercise_insights.core.get_exercise_metrics")
    def test_refresh_instruction_is_one_shot(self, mock_get_metrics):
        mock_get_metrics.return_value = {"training_load": {"7d": 5}}
        self.client.post("/ask", json={"question": "/refresh-data"})
        self.client.post("/ask", json={"question": "first question"})

        self.client.post("/ask", json={"question": "second question"})

        extra_system = self.recording_agent.calls[1]["extra_system"]
        self.assertNotIn("force-refreshed", extra_system)

    def test_new_messages_are_persisted(self):
        self.client.post("/ask", json={"question": "hi"})

        history = context_store.get_history(self.user_id)["messages"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["content"], "hi")

    def test_usage_is_persisted_after_ask(self):
        self.client.post("/ask", json={"question": "hi"})

        summary = context_store.get_usage_summary(self.user_id)
        self.assertEqual(summary["today"]["requests"], 1)
        self.assertEqual(summary["today"]["input_tokens"], 100)
        self.assertEqual(summary["today"]["output_tokens"], 20)

    def test_question_too_long_is_rejected(self):
        resp = self.client.post("/ask", json={"question": "x" * 4001})

        self.assertEqual(resp.status_code, 422)
        self.assertEqual(self.recording_agent.calls, [])

    def test_empty_question_is_rejected(self):
        resp = self.client.post("/ask", json={"question": ""})

        self.assertEqual(resp.status_code, 422)

    def test_existing_plan_is_injected_as_context_but_not_editable_here(self):
        context_store.save_plan(self.user_id, start_date="2026-08-10", weeks=[], themes=[])

        self.client.post("/ask", json={"question": "how's my plan looking?"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("2026-08-10", extra_system)
        self.assertIn("training plan page", extra_system)

    def test_no_plan_does_not_mention_a_plan_at_all(self):
        self.client.post("/ask", json={"question": "hi"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertNotIn("training plan", extra_system)


class TestPlanPageAuthGating(AppTestCase):
    def test_plan_page_redirects_when_unauthenticated(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.get("/plan", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")

    def test_plan_page_served_when_authenticated(self):
        resp = self.client.get("/plan")

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Training Plan", resp.content)

    def test_plan_data_requires_auth(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.get("/plan/data")

        self.assertEqual(resp.status_code, 401)

    def test_plan_edit_requires_auth(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.post(
            "/plan/edit", json={"start_date": "2026-08-10", "weeks": [], "themes": []}
        )

        self.assertEqual(resp.status_code, 401)

    def test_plan_ask_requires_auth(self):
        anon_client = TestClient(app_module.app)

        resp = anon_client.post("/plan/ask", json={"question": "hi"})

        self.assertEqual(resp.status_code, 401)


class TestPlanDataEndpoint(AppTestCase):
    def test_no_plan_yet_returns_null_plan_and_empty_actuals(self):
        resp = self.client.get("/plan/data")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"plan": None, "actuals": []})

    @patch("exercise_insights.core.get_weekly_actuals")
    def test_existing_plan_returns_plan_and_live_computed_actuals(self, mock_actuals):
        context_store.save_plan(
            self.user_id,
            start_date="2026-08-10",
            weeks=[{"planned_distance_miles": 30, "planned_duration_hr": 4.0, "planned_elevation_gain_ft": 1500}],
            themes=[],
        )
        mock_actuals.return_value = [
            {"actual_distance_miles": 28, "actual_duration_hr": 3.8, "actual_elevation_gain_ft": 1400}
        ]

        resp = self.client.get("/plan/data")

        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["plan"]["start_date"], "2026-08-10")
        self.assertEqual(body["actuals"], mock_actuals.return_value)
        mock_actuals.assert_called_once_with("polar-user-1", "2026-08-10", 1)


class TestPlanEditEndpoint(AppTestCase):
    def test_valid_plan_is_persisted(self):
        resp = self.client.post(
            "/plan/edit",
            json={
                "start_date": "2026-08-10",
                "weeks": [
                    {"planned_distance_miles": 30, "planned_duration_hr": 4.0, "planned_elevation_gain_ft": 1500}
                ],
                "themes": [{"label": "Base building", "weeks": [0], "color": "#3987e5"}],
            },
        )

        self.assertEqual(resp.status_code, 200)
        plan = context_store.get_plan(self.user_id)
        self.assertEqual(plan["start_date"], "2026-08-10")
        self.assertEqual(plan["themes"][0]["label"], "Base building")

    def test_theme_week_out_of_range_is_rejected(self):
        resp = self.client.post(
            "/plan/edit",
            json={
                "start_date": "2026-08-10",
                "weeks": [
                    {"planned_distance_miles": 30, "planned_duration_hr": 4.0, "planned_elevation_gain_ft": 1500}
                ],
                "themes": [{"label": "Bad", "weeks": [5], "color": "#3987e5"}],
            },
        )

        self.assertEqual(resp.status_code, 422)
        self.assertIsNone(context_store.get_plan(self.user_id))

    def test_no_weeks_is_rejected(self):
        resp = self.client.post(
            "/plan/edit", json={"start_date": "2026-08-10", "weeks": [], "themes": []}
        )

        self.assertEqual(resp.status_code, 422)

    def test_edit_replaces_the_whole_plan_not_a_merge(self):
        self.client.post(
            "/plan/edit",
            json={
                "start_date": "2026-08-10",
                "weeks": [
                    {"planned_distance_miles": 30, "planned_duration_hr": 4.0, "planned_elevation_gain_ft": 1500},
                    {"planned_distance_miles": 35, "planned_duration_hr": 4.5, "planned_elevation_gain_ft": 1600},
                ],
                "themes": [],
            },
        )

        self.client.post(
            "/plan/edit",
            json={
                "start_date": "2026-08-10",
                "weeks": [
                    {"planned_distance_miles": 40, "planned_duration_hr": 5.0, "planned_elevation_gain_ft": 1700}
                ],
                "themes": [],
            },
        )

        plan = context_store.get_plan(self.user_id)
        self.assertEqual(len(plan["weeks"]), 1)


class TestPlanAskRouting(AppTestCase):
    def test_plain_question_reaches_the_agent_with_the_plan_persona(self):
        resp = self.client.post("/plan/ask", json={"question": "help me build a plan"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.recording_agent.calls), 1)
        call = self.recording_agent.calls[0]
        self.assertEqual(call["question"], "help me build a plan")
        self.assertEqual(call["base_system"], settings.plan_system_prompt)

    def test_no_plan_yet_injects_a_create_one_instruction(self):
        self.client.post("/plan/ask", json={"question": "hi"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("doesn't have a training plan yet", extra_system)

    def test_existing_plan_is_injected_as_context(self):
        context_store.save_plan(self.user_id, start_date="2026-08-10", weeks=[], themes=[])

        self.client.post("/plan/ask", json={"question": "push the taper out a week"})

        extra_system = self.recording_agent.calls[0]["extra_system"]
        self.assertIn("2026-08-10", extra_system)

    def test_new_messages_persist_under_the_plan_conversation_kind_not_the_coach_ones(self):
        self.client.post("/plan/ask", json={"question": "hi"})

        plan_history = context_store.get_history(self.user_id, kind="plan_conversation")["messages"]
        coach_history = context_store.get_history(self.user_id)["messages"]
        self.assertEqual(len(plan_history), 2)
        self.assertEqual(coach_history, [])

    def test_no_slash_command_routing(self):
        # Unlike /ask, /plan/ask has no commands.is_command() interception --
        # a message starting with "/" is just sent to the agent as-is.
        self.client.post("/plan/ask", json={"question": "/profile"})

        self.assertEqual(len(self.recording_agent.calls), 1)
        self.assertEqual(self.recording_agent.calls[0]["question"], "/profile")


class TestLoginFlow(AppTestCase):
    def test_successful_login_sets_cookie_and_redirects(self):
        fake_session = MagicMock()
        fake_session.user.id = "new-user"
        fake_session.user.email = "athlete@example.com"
        fake_session.access_token = "tok"
        fake_session.refresh_token = "refresh"
        fake_session.expires_at = None
        fake_result = MagicMock(session=fake_session)

        with patch.object(app_module, "_get_supabase") as mock_get_supabase:
            mock_get_supabase.return_value.auth.sign_in_with_password.return_value = fake_result
            anon_client = TestClient(app_module.app)
            resp = anon_client.post(
                "/auth/login",
                data={"email": "athlete@example.com", "password": "secret"},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/")
        self.assertIn(settings.auth_cookie_name, resp.cookies)

    def test_failed_login_redirects_with_generic_error(self):
        with patch.object(app_module, "_get_supabase") as mock_get_supabase:
            mock_get_supabase.return_value.auth.sign_in_with_password.side_effect = AuthApiError(
                "Invalid login credentials", 400, "invalid_credentials"
            )
            anon_client = TestClient(app_module.app)
            resp = anon_client.post(
                "/auth/login",
                data={"email": "athlete@example.com", "password": "wrong"},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].startswith("/login?error="))

    def test_no_session_returned_redirects_with_generic_error(self):
        fake_result = MagicMock(session=None)

        with patch.object(app_module, "_get_supabase") as mock_get_supabase:
            mock_get_supabase.return_value.auth.sign_in_with_password.return_value = fake_result
            anon_client = TestClient(app_module.app)
            resp = anon_client.post(
                "/auth/login",
                data={"email": "athlete@example.com", "password": "secret"},
                follow_redirects=False,
            )

        self.assertEqual(resp.status_code, 303)
        self.assertTrue(resp.headers["location"].startswith("/login?error="))

    def test_logout_clears_session(self):
        resp = self.client.post("/auth/logout", follow_redirects=False)

        self.assertEqual(resp.status_code, 303)
        self.assertEqual(resp.headers["location"], "/login")
        self.assertNotIn(self.session_id, app_module._sessions)


if __name__ == "__main__":
    unittest.main()

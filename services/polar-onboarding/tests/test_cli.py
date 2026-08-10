import contextlib
import io
import os
import unittest
from unittest.mock import patch

from src.cli import (
    build_parser,
    cmd_authorize,
    cmd_register,
    cmd_webhook_create,
    cmd_webhook_delete,
    cmd_webhook_get,
    cmd_webhook_update,
    main,
)


def _parse(argv):
    return build_parser().parse_args(argv)


class TestArgumentWiring(unittest.TestCase):
    def test_authorize_requires_client_id_and_secret(self):
        args = _parse(["authorize", "--client-id", "cid", "--client-secret", "csecret"])

        self.assertEqual(args.func, cmd_authorize)
        self.assertEqual(args.client_id, "cid")
        self.assertIsNone(args.redirect_uri)

    def test_authorize_missing_client_secret_defaults_to_none_without_env_var(self):
        with patch.dict(os.environ, {}, clear=True):
            args = _parse(["authorize", "--client-id", "cid"])

        self.assertIsNone(args.client_secret)

    def test_client_id_flag_falls_back_to_env_var_when_omitted(self):
        with patch.dict(os.environ, {"POLAR_CLIENT_ID": "env-cid"}, clear=True):
            args = _parse(["authorize", "--client-secret", "csecret"])

        self.assertEqual(args.client_id, "env-cid")

    def test_client_id_flag_overrides_env_var_when_both_given(self):
        with patch.dict(os.environ, {"POLAR_CLIENT_ID": "env-cid"}, clear=True):
            args = _parse(["authorize", "--client-id", "flag-cid", "--client-secret", "csecret"])

        self.assertEqual(args.client_id, "flag-cid")

    def test_register_wires_access_token_and_member_id(self):
        args = _parse(["register", "--access-token", "tok", "--member-id", "42"])

        self.assertEqual(args.func, cmd_register)
        self.assertEqual(args.access_token, "tok")
        self.assertEqual(args.member_id, "42")

    def test_webhook_create_defaults_region_and_wires_func(self):
        args = _parse(
            [
                "webhook",
                "create",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
                "--callback-url",
                "https://example.com/webhook",
                "--events",
                "EXERCISE,SLEEP",
            ]
        )

        self.assertEqual(args.func, cmd_webhook_create)
        self.assertEqual(args.region, "us-east-1")
        self.assertIsNone(args.store_secret_name)

    def test_webhook_requires_a_subcommand(self):
        with self.assertRaises(SystemExit):
            _parse(["webhook"])


class TestCmdAuthorize(unittest.TestCase):
    @patch("src.cli.exchange_code_for_token")
    @patch("src.cli.extract_code")
    @patch("builtins.input", return_value="pasted-code-or-url")
    @patch("src.cli.build_authorize_url")
    def test_prints_authorize_url_then_exchanges_pasted_code(
        self, mock_build_url, mock_input, mock_extract_code, mock_exchange
    ):
        mock_build_url.return_value = "https://flow.polar.com/oauth2/authorization?client_id=cid"
        mock_extract_code.return_value = "real-code"
        mock_exchange.return_value = {"access_token": "abc", "x_user_id": 123}
        args = _parse(["authorize", "--client-id", "cid", "--client-secret", "csecret"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_authorize(args)

        mock_extract_code.assert_called_once_with("pasted-code-or-url")
        mock_exchange.assert_called_once_with(
            client_id="cid", client_secret="csecret", code="real-code", redirect_uri=None
        )
        self.assertIn("https://flow.polar.com/oauth2/authorization?client_id=cid", out.getvalue())
        self.assertIn("abc", out.getvalue())

    def test_missing_client_id_and_env_var_exits_with_clear_message(self):
        with patch.dict(os.environ, {}, clear=True):
            args = _parse(["authorize", "--client-secret", "csecret"])

        with self.assertRaises(SystemExit) as ctx:
            cmd_authorize(args)

        self.assertIn("--client-id", str(ctx.exception))
        self.assertIn("POLAR_CLIENT_ID", str(ctx.exception))


class TestCmdRegister(unittest.TestCase):
    @patch("src.cli.register_user")
    def test_prints_registration_result_as_json(self, mock_register_user):
        mock_register_user.return_value = {"polar-user-id": 42}
        args = _parse(["register", "--access-token", "tok", "--member-id", "42"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_register(args)

        mock_register_user.assert_called_once_with(access_token="tok", member_id="42")
        self.assertIn('"polar-user-id": 42', out.getvalue())


class TestCmdWebhookCreate(unittest.TestCase):
    def _args(self, store_secret_name=None, aws_profile=None):
        argv = [
            "webhook",
            "create",
            "--client-id",
            "cid",
            "--client-secret",
            "csecret",
            "--callback-url",
            "https://example.com/webhook",
            "--events",
            "EXERCISE,SLEEP",
        ]
        if store_secret_name:
            argv += ["--store-secret-name", store_secret_name]
        if aws_profile:
            argv += ["--aws-profile", aws_profile]
        return _parse(argv)

    @patch("src.cli.create_webhook")
    def test_splits_comma_separated_events_before_calling_create_webhook(self, mock_create):
        mock_create.return_value = {"data": {"webhook_id": 1}}

        with contextlib.redirect_stdout(io.StringIO()):
            cmd_webhook_create(self._args())

        mock_create.assert_called_once_with(
            client_id="cid",
            client_secret="csecret",
            callback_url="https://example.com/webhook",
            events=["EXERCISE", "SLEEP"],
        )

    @patch("src.cli.create_webhook")
    def test_without_store_secret_name_warns_and_does_not_store(self, mock_create):
        mock_create.return_value = {"data": {"signature_secret_key": "shh"}}

        with patch("src.cli.set_secret_keys") as mock_set_secret_keys:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cmd_webhook_create(self._args())

        mock_set_secret_keys.assert_not_called()
        self.assertIn("not saved anywhere", out.getvalue())

    @patch("src.cli.set_secret_keys")
    @patch("src.cli.create_webhook")
    def test_with_store_secret_name_and_key_present_stores_it(self, mock_create, mock_set_secret_keys):
        # Polar's real response wraps the object in a "data" envelope -
        # this must be the nested shape, not a flat top-level key, or this
        # test won't catch a regression of the extraction-path bug.
        mock_create.return_value = {"data": {"signature_secret_key": "shh"}}

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_webhook_create(self._args(store_secret_name="prod/polarWebhook"))

        mock_set_secret_keys.assert_called_once_with(
            "prod/polarWebhook", "us-east-1", {"POLAR_WEBHOOK": "shh"}, profile_name=None
        )
        self.assertIn("Stored signature_secret_key", out.getvalue())

    @patch("src.cli.set_secret_keys")
    @patch("src.cli.create_webhook")
    def test_aws_profile_flag_reaches_set_secret_keys(self, mock_create, mock_set_secret_keys):
        mock_create.return_value = {"data": {"signature_secret_key": "shh"}}

        with contextlib.redirect_stdout(io.StringIO()):
            cmd_webhook_create(
                self._args(store_secret_name="prod/polarWebhook", aws_profile="polar-app-prod")
            )

        mock_set_secret_keys.assert_called_once_with(
            "prod/polarWebhook",
            "us-east-1",
            {"POLAR_WEBHOOK": "shh"},
            profile_name="polar-app-prod",
        )

    @patch("src.cli.set_secret_keys")
    @patch("src.cli.create_webhook")
    def test_aws_profile_env_var_fallback_reaches_set_secret_keys(
        self, mock_create, mock_set_secret_keys
    ):
        mock_create.return_value = {"data": {"signature_secret_key": "shh"}}

        with patch.dict(os.environ, {"AWS_PROFILE": "polar-app-prod"}, clear=True):
            args = self._args(store_secret_name="prod/polarWebhook")
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_webhook_create(args)

        mock_set_secret_keys.assert_called_once_with(
            "prod/polarWebhook",
            "us-east-1",
            {"POLAR_WEBHOOK": "shh"},
            profile_name="polar-app-prod",
        )

    @patch("src.cli.set_secret_keys")
    @patch("src.cli.create_webhook")
    def test_with_store_secret_name_but_no_key_in_response_warns_on_stderr(
        self, mock_create, mock_set_secret_keys
    ):
        # Documents real behavior: a webhook-create response missing
        # signature_secret_key must not silently store nothing under that key.
        mock_create.return_value = {"data": {"webhook_id": 1}}

        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            cmd_webhook_create(self._args(store_secret_name="prod/polarWebhook"))

        mock_set_secret_keys.assert_not_called()
        self.assertIn("no signature_secret_key", err.getvalue())


class TestCmdWebhookOthers(unittest.TestCase):
    @patch("src.cli.update_webhook")
    def test_update_splits_events_and_forwards_webhook_id(self, mock_update):
        mock_update.return_value = {"data": {}}
        args = _parse(
            [
                "webhook",
                "update",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
                "--webhook-id",
                "wh-1",
                "--callback-url",
                "https://example.com/webhook",
                "--events",
                "EXERCISE",
            ]
        )

        with contextlib.redirect_stdout(io.StringIO()):
            cmd_webhook_update(args)

        mock_update.assert_called_once_with(
            client_id="cid",
            client_secret="csecret",
            webhook_id="wh-1",
            callback_url="https://example.com/webhook",
            events=["EXERCISE"],
        )

    @patch("src.cli.get_webhooks")
    def test_get_prints_result_as_json(self, mock_get_webhooks):
        mock_get_webhooks.return_value = {"data": [{"webhook_id": 1}]}
        args = _parse(["webhook", "get", "--client-id", "cid", "--client-secret", "csecret"])

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_webhook_get(args)

        mock_get_webhooks.assert_called_once_with("cid", "csecret")
        self.assertIn("webhook_id", out.getvalue())

    @patch("src.cli.delete_webhook")
    def test_delete_forwards_args_and_confirms(self, mock_delete_webhook):
        args = _parse(
            [
                "webhook",
                "delete",
                "--client-id",
                "cid",
                "--client-secret",
                "csecret",
                "--webhook-id",
                "wh-1",
            ]
        )

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_webhook_delete(args)

        mock_delete_webhook.assert_called_once_with("cid", "csecret", "wh-1")
        self.assertIn("Deleted.", out.getvalue())


class TestMain(unittest.TestCase):
    @patch("src.cli.register_user")
    def test_parses_real_argv_and_dispatches_to_the_right_command(self, mock_register_user):
        mock_register_user.return_value = {"polar-user-id": 1}

        with patch(
            "sys.argv", ["polar-onboarding", "register", "--access-token", "tok", "--member-id", "1"]
        ):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                main()

        mock_register_user.assert_called_once_with(access_token="tok", member_id="1")


if __name__ == "__main__":
    unittest.main()

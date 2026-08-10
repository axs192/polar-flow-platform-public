import unittest
from unittest.mock import patch

from src.app.main import lambda_handler, run_app


class TestRunApp(unittest.TestCase):
    @patch("src.app.main.setup_logging")
    def test_logging_setup_failure_raises_before_any_helper_call(self, mock_setup_logging):
        mock_setup_logging.side_effect = Exception("logging misconfigured")

        with patch("src.app.main.Daily_Helper") as mock_helper_cls:
            with self.assertRaises(Exception):
                run_app()

        mock_helper_cls.assert_not_called()

    @patch("src.app.main.Daily_Helper")
    def test_success_path_reports_complete(self, mock_helper_cls):
        result = run_app()

        mock_helper_cls.return_value.upload_daily_load.assert_called_once()
        mock_helper_cls.return_value.send_daily_notification.assert_called_once()
        self.assertEqual(result, {"message": "Script Complete."})

    @patch("src.app.main.Daily_Helper")
    def test_upload_runs_before_notification(self, mock_helper_cls):
        # Upload must land first - it's the idempotent, safe-to-retry side
        # effect, while notification is the terminal step so a message is
        # only deleted from SQS (no retry) once it's actually sent.
        call_order = []
        mock_helper_cls.return_value.upload_daily_load.side_effect = lambda: call_order.append(
            "upload"
        )
        mock_helper_cls.return_value.send_daily_notification.side_effect = lambda: call_order.append(
            "notify"
        )

        run_app()

        self.assertEqual(call_order, ["upload", "notify"])

    @patch("src.app.main.Daily_Helper")
    def test_notification_failure_raises_after_upload_already_ran(self, mock_helper_cls):
        # A notification failure must still raise (so SQS retries) - but
        # upload runs first, so the retry re-runs an idempotent overwrite
        # rather than skipping data that already landed.
        mock_helper_cls.return_value.send_daily_notification.side_effect = Exception(
            "WhatsApp API down"
        )

        with self.assertRaises(Exception):
            run_app()

        mock_helper_cls.return_value.upload_daily_load.assert_called_once()

    @patch("src.app.main.Daily_Helper")
    def test_upload_failure_raises(self, mock_helper_cls):
        mock_helper_cls.return_value.upload_daily_load.side_effect = Exception(
            "ProvisionedThroughputExceeded"
        )

        with self.assertRaises(Exception):
            run_app()

        mock_helper_cls.return_value.send_daily_notification.assert_not_called()


class TestLambdaHandler(unittest.TestCase):
    @patch("src.app.main.run_app")
    def test_delegates_directly_to_run_app_regardless_of_event_shape(self, mock_run_app):
        mock_run_app.return_value = {"message": "Script Complete."}

        result = lambda_handler(event={"anything": "at all"}, context=None)

        mock_run_app.assert_called_once_with()
        self.assertEqual(result, {"message": "Script Complete."})


if __name__ == "__main__":
    unittest.main()

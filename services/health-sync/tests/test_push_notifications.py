import os
import unittest
from unittest.mock import patch

import responses
from src.app.messaging.push_notifications import Push_Notification

NO_DATA = {"No_Data": 1}


class TestPushNotification(unittest.TestCase):
    def setUp(self):
        os.environ["TO_MOBILE"] = "whatsapp:+10000000000"
        os.environ["FROM_MOBILE"] = "0000000000000"

        self.config_patcher = patch("src.app.messaging.push_notifications.config_loader")
        mock_config_loader = self.config_patcher.start()
        mock_config_loader.return_value = {"META_AUTH": "test-token"}

        self.url = "https://graph.facebook.com/v22.0/0000000000000/messages"

    def tearDown(self):
        self.config_patcher.stop()
        del os.environ["TO_MOBILE"]
        del os.environ["FROM_MOBILE"]

    @responses.activate
    def test_send_note_on_200_logs_success(self):
        responses.add(
            responses.POST,
            self.url,
            json={
                "messaging_product": "whatsapp",
                "contacts": [{"input": "+10000000000", "wa_id": "10000000000"}],
                "messages": [{"id": "wamid.EXAMPLE123"}],
            },
            status=200,
        )

        Push_Notification(NO_DATA).send_note()

        self.assertEqual(len(responses.calls), 1)
        sent_body = responses.calls[0].request.body.decode()
        self.assertIn("daily_update", sent_body)
        self.assertEqual(responses.calls[0].request.headers["Authorization"], "Bearer test-token")

    @responses.activate
    def test_send_note_on_400_does_not_raise(self):
        responses.add(
            responses.POST,
            self.url,
            json={
                "error": {
                    "message": "Invalid parameter",
                    "type": "OAuthException",
                    "code": 100,
                }
            },
            status=400,
        )

        with self.assertLogs(level="ERROR") as log:
            Push_Notification(NO_DATA).send_note()

        self.assertEqual(len(responses.calls), 1)
        self.assertIn("OAuthException", "".join(log.output))


if __name__ == "__main__":
    unittest.main()

import os
import unittest
from unittest.mock import patch

import responses
from exercise_insights.whatsapp_adapter.push_notification import Push_Notification


class TestPushNotification(unittest.TestCase):
    def setUp(self):
        os.environ["TO_MOBILE"] = "whatsapp:+10000000000"
        os.environ["FROM_MOBILE"] = "0000000000000"
        os.environ["MAX_LEN"] = "4096"

        self.config_patcher = patch("exercise_insights.whatsapp_adapter.push_notification.config_loader")
        self.config_patcher.start().return_value = {"META_AUTH": "test-token"}

        self.url = "https://graph.facebook.com/v22.0/0000000000000/messages"

    def tearDown(self):
        self.config_patcher.stop()
        for key in ("TO_MOBILE", "FROM_MOBILE", "MAX_LEN"):
            del os.environ[key]

    @responses.activate
    def test_send_note_on_200_sends_full_message(self):
        responses.add(
            responses.POST,
            self.url,
            json={"messaging_product": "whatsapp", "messages": [{"id": "wamid.EXAMPLE"}]},
            status=200,
        )

        Push_Notification().send_note("Short message")

        self.assertEqual(len(responses.calls), 1)
        sent_body = responses.calls[0].request.body.decode()
        self.assertIn("Short message", sent_body)

    @responses.activate
    def test_send_note_on_400_logs_error_and_does_not_raise(self):
        responses.add(
            responses.POST,
            self.url,
            json={"error": {"message": "Invalid parameter", "type": "OAuthException"}},
            status=400,
        )

        with self.assertLogs(level="ERROR") as log:
            Push_Notification().send_note("Short message")

        self.assertEqual(len(responses.calls), 1)
        self.assertIn("OAuthException", "".join(log.output))

    @responses.activate
    def test_send_note_splits_message_over_max_len(self):
        os.environ["MAX_LEN"] = "20"
        responses.add(
            responses.POST,
            self.url,
            json={"messaging_product": "whatsapp"},
            status=200,
        )

        long_message = "This is a long message that needs splitting"
        Push_Notification().send_note(long_message)

        self.assertGreaterEqual(len(responses.calls), 2)
        rejoined = "".join(call.request.body.decode() for call in responses.calls)
        for word in long_message.split():
            self.assertIn(word, rejoined)


if __name__ == "__main__":
    unittest.main()

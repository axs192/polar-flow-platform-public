import os
import unittest
from unittest.mock import patch

from exercise_insights.whatsapp_adapter.lambda_handler import lambda_handler


class TestLambdaHandler(unittest.TestCase):
    def setUp(self):
        os.environ["POLAR_USER_ID"] = "user-1"

    def tearDown(self):
        del os.environ["POLAR_USER_ID"]

    @patch("exercise_insights.whatsapp_adapter.lambda_handler.setup_logging")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.Push_Notification")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.answer_question")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.extract_sqs_message")
    def test_question_is_answered_and_sent(
        self, mock_extract, mock_answer, mock_push_cls, mock_setup_logging
    ):
        mock_extract.return_value = "How did I run this week?"
        mock_answer.return_value = "You ran 3 times this week."
        mock_push_instance = mock_push_cls.return_value

        lambda_handler({"Records": []}, None)

        mock_answer.assert_called_once_with(user_id="user-1", question="How did I run this week?")
        mock_push_instance.send_note.assert_called_once_with(message="You ran 3 times this week.")

    @patch("exercise_insights.whatsapp_adapter.lambda_handler.setup_logging")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.Push_Notification")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.answer_question")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.extract_sqs_message")
    def test_blank_question_does_not_call_answer_question(
        self, mock_extract, mock_answer, mock_push_cls, mock_setup_logging
    ):
        mock_extract.return_value = "   "

        lambda_handler({"Records": []}, None)

        mock_answer.assert_not_called()
        mock_push_cls.assert_not_called()

    @patch("exercise_insights.whatsapp_adapter.lambda_handler.setup_logging")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.Push_Notification")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.answer_question")
    @patch("exercise_insights.whatsapp_adapter.lambda_handler.extract_sqs_message")
    def test_error_during_processing_raises(
        self, mock_extract, mock_answer, mock_push_cls, mock_setup_logging
    ):
        mock_extract.return_value = "How did I run this week?"
        mock_answer.side_effect = Exception("OpenAI error")

        with self.assertRaises(Exception):
            lambda_handler({"Records": []}, None)

    @patch(
        "exercise_insights.whatsapp_adapter.lambda_handler.setup_logging",
        side_effect=Exception("logging config error"),
    )
    def test_logging_setup_failure_raises(self, mock_setup_logging):
        with self.assertRaises(Exception):
            lambda_handler({"Records": []}, None)


if __name__ == "__main__":
    unittest.main()

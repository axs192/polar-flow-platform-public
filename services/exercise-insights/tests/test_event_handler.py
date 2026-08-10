import json
import unittest

from exercise_insights.whatsapp_adapter.event_handler import extract_sqs_message


class TestExtractSqsMessage(unittest.TestCase):
    def test_extracts_plain_text_body(self):
        event = {"Records": [{"body": "How was my run today?"}]}
        self.assertEqual(extract_sqs_message(event), "How was my run today?")

    def test_extracts_json_body_as_string(self):
        event = {"Records": [{"body": json.dumps({"message": "hello"})}]}
        self.assertEqual(extract_sqs_message(event), "{'message': 'hello'}")

    def test_skips_records_with_no_body(self):
        event = {"Records": [{"body": ""}, {"body": "second record"}]}
        self.assertEqual(extract_sqs_message(event), "second record")

    def test_no_records_returns_empty_string(self):
        self.assertEqual(extract_sqs_message({"Records": []}), "")

    def test_event_as_json_string_is_parsed(self):
        event = json.dumps({"Records": [{"body": "from a string event"}]})
        self.assertEqual(extract_sqs_message(event), "from a string event")

    def test_non_json_string_event_returned_as_is(self):
        self.assertEqual(extract_sqs_message("not json"), "not json")

    def test_malformed_event_does_not_raise(self):
        self.assertEqual(extract_sqs_message(None), "")


if __name__ == "__main__":
    unittest.main()

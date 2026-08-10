import json
import unittest
from unittest.mock import patch

from src.app.main import lambda_handler, run_app


def _sqs_event(body):
    return {"Records": [{"body": body if isinstance(body, str) else json.dumps(body)}]}


class TestRunApp(unittest.TestCase):
    @patch.dict("os.environ", {"TABLE_NAME": "exercise_data"})
    @patch("src.app.main.loader")
    @patch("src.app.main.load_creator")
    @patch("src.app.main.Extractor")
    def test_success_path_uploads_and_reports_complete(
        self, mock_extractor_cls, mock_load_creator, mock_loader_cls
    ):
        mock_extractor_cls.return_value.get_specifc_exercise.return_value = {"id": "ex-1"}
        mock_load_creator.return_value.create_load.return_value = {
            "uid": "user-1",
            "exerciseID": "ex-1",
        }
        mock_loader = mock_loader_cls.return_value

        result = run_app(exerciseId="ex-1")

        mock_load_creator.assert_called_once_with(response={"id": "ex-1"})
        mock_loader.exists.assert_called_once_with(table_name="exercise_data")
        mock_loader.add_record.assert_called_once_with(load={"uid": "user-1", "exerciseID": "ex-1"})
        self.assertEqual(result, {"message": "Script Complete."})

    @patch("src.app.main.Extractor")
    def test_extractor_failure_raises(self, mock_extractor_cls):
        mock_extractor_cls.return_value.get_specifc_exercise.side_effect = Exception("API error")

        with self.assertRaises(Exception):
            run_app(exerciseId="ex-1")

    @patch("src.app.main.load_creator")
    @patch("src.app.main.Extractor")
    def test_transform_failure_raises(self, mock_extractor_cls, mock_load_creator):
        mock_extractor_cls.return_value.get_specifc_exercise.return_value = {"id": "ex-1"}
        mock_load_creator.return_value.create_load.side_effect = Exception("bad shape")

        with self.assertRaises(Exception):
            run_app(exerciseId="ex-1")

    @patch("src.app.main.load_creator")
    @patch("src.app.main.Extractor")
    def test_missing_table_name_env_var_raises(self, mock_extractor_cls, mock_load_creator):
        # TABLE_NAME deliberately not set - exercises the os.environ[...] KeyError path.
        mock_extractor_cls.return_value.get_specifc_exercise.return_value = {"id": "ex-1"}
        mock_load_creator.return_value.create_load.return_value = {"uid": "user-1"}

        with self.assertRaises(KeyError):
            run_app(exerciseId="ex-1")

    @patch.dict("os.environ", {"TABLE_NAME": "exercise_data"})
    @patch("src.app.main.loader")
    @patch("src.app.main.load_creator")
    @patch("src.app.main.Extractor")
    def test_dynamo_upload_failure_raises(
        self, mock_extractor_cls, mock_load_creator, mock_loader_cls
    ):
        mock_extractor_cls.return_value.get_specifc_exercise.return_value = {"id": "ex-1"}
        mock_load_creator.return_value.create_load.return_value = {"uid": "user-1"}
        mock_loader_cls.return_value.add_record.side_effect = Exception("ProvisionedThroughput")

        with self.assertRaises(Exception):
            run_app(exerciseId="ex-1")


class TestLambdaHandler(unittest.TestCase):
    @patch("src.app.main.run_app")
    def test_dict_event_extracts_entity_id_and_delegates_to_run_app(self, mock_run_app):
        mock_run_app.return_value = {"message": "Script Complete."}
        event = _sqs_event({"entity_id": "ex-1"})

        result = lambda_handler(event, context=None)

        mock_run_app.assert_called_once_with(exerciseId="ex-1")
        self.assertEqual(result, {"message": "Script Complete."})

    @patch("src.app.main.run_app")
    def test_string_encoded_event_is_parsed_before_dispatch(self, mock_run_app):
        mock_run_app.return_value = {"message": "Script Complete."}
        event = json.dumps(_sqs_event({"entity_id": "ex-2"}))

        lambda_handler(event, context=None)

        mock_run_app.assert_called_once_with(exerciseId="ex-2")

    @patch("src.app.main.run_app")
    def test_double_encoded_body_is_unwrapped_before_dispatch(self, mock_run_app):
        # Records[0].body is itself a JSON string, and that string's contents
        # (after one json.loads) is still a string, not a dict - exercises the
        # second `if isinstance(data, str): data = json.loads(data)` branch.
        mock_run_app.return_value = {"message": "Script Complete."}
        inner = json.dumps({"entity_id": "ex-3"})
        event = {"Records": [{"body": json.dumps(inner)}]}

        lambda_handler(event, context=None)

        mock_run_app.assert_called_once_with(exerciseId="ex-3")

    @patch("src.app.main.run_app")
    def test_missing_records_key_raises(self, mock_run_app):
        with self.assertRaises(KeyError):
            lambda_handler({}, context=None)

        mock_run_app.assert_not_called()

    @patch("src.app.main.run_app")
    def test_body_without_entity_id_dispatches_with_none(self, mock_run_app):
        mock_run_app.return_value = {"message": "Script Complete."}
        event = _sqs_event({"some_other_field": "value"})

        lambda_handler(event, context=None)

        mock_run_app.assert_called_once_with(exerciseId=None)


if __name__ == "__main__":
    unittest.main()

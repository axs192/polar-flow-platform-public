import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import responses
from requests.exceptions import HTTPError
from src.app.ETL.extractor import Extractor

BASE_URL = "https://www.polaraccesslink.com/v3"
FULL_CONFIG = {
    "client_id": "cid",
    "client_secret": "csecret",
    "access_token": "token-123",
    "user_id": "user-1",
}


def _extractor(config=FULL_CONFIG):
    with patch("src.app.ETL.extractor.config_loader", return_value=config):
        return Extractor()


class TestExtractorInit(unittest.TestCase):
    def test_config_loader_failure_reraises(self):
        with patch(
            "src.app.ETL.extractor.config_loader",
            side_effect=RuntimeError("Secrets Manager down"),
        ), self.assertRaises(RuntimeError):
            Extractor()

    def test_missing_access_token_skips_accesslink_setup(self):
        extractor = _extractor(config={"client_id": "cid", "client_secret": "csecret"})

        self.assertFalse(hasattr(extractor, "accesslink"))

    def test_accesslink_init_failure_reraises(self):
        with (
            patch("src.app.ETL.extractor.config_loader", return_value=FULL_CONFIG),
            patch("src.app.ETL.extractor.AccessLink", side_effect=ValueError("bad creds")),
            self.assertRaises(ValueError),
        ):
            Extractor()


class TestGetExercises(unittest.TestCase):
    @responses.activate
    def test_success_returns_list_via_real_http_response(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises?samples=True&zones=True&route=False",
            json=[{"id": "ex-1"}, {"id": "ex-2"}],
            status=200,
        )

        result = _extractor().get_exercises()

        self.assertEqual(result, [{"id": "ex-1"}, {"id": "ex-2"}])

    @responses.activate
    def test_401_returns_empty_list_not_an_exception(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises?samples=True&zones=True&route=False",
            json={"error": "unauthorized"},
            status=401,
        )

        result = _extractor().get_exercises()

        self.assertEqual(result, [])


class TestGetSpecificExercise(unittest.TestCase):
    def test_none_exercise_id_returns_none(self):
        result = _extractor().get_specifc_exercise(exerciseId=None)

        self.assertIsNone(result)

    @responses.activate
    def test_404_returns_empty_dict_not_an_exception(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises/ex-1?samples=True&zones=True&route=False",
            json={"error": "not_found"},
            status=404,
        )

        result = _extractor().get_specifc_exercise(exerciseId="ex-1")

        self.assertEqual(result, {})


class TestGetSpecificExerciseFitFile(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.fit_path = Path(self._tmpdir.name) / "test_exercise.fit"
        os.environ["FIT_FILE"] = str(self.fit_path)

    def tearDown(self):
        del os.environ["FIT_FILE"]
        self._tmpdir.cleanup()

    def test_none_exercise_id_returns_none(self):
        result = _extractor().get_specifc_exercise_FIT_file(exerciseId=None)

        self.assertIsNone(result)

    @responses.activate
    def test_success_writes_fit_bytes_to_configured_path(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises/ex-1/fit",
            body=b"\x0e\x10FIT-binary-payload",
            status=200,
            content_type="application/octet-stream",
        )

        result = _extractor().get_specifc_exercise_FIT_file(exerciseId="ex-1")

        self.assertTrue(result)
        self.assertEqual(self.fit_path.read_bytes(), b"\x0e\x10FIT-binary-payload")

    @responses.activate
    def test_empty_fit_payload_returns_none_without_writing_a_file(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises/ex-1/fit",
            body=b"",
            status=200,
            content_type="application/octet-stream",
        )

        result = _extractor().get_specifc_exercise_FIT_file(exerciseId="ex-1")

        self.assertIsNone(result)
        self.assertFalse(self.fit_path.exists())

    @responses.activate
    def test_http_error_is_logged_and_reraised(self):
        # Unlike get_exercises/get_specifc_exercise, this method re-raises on
        # failure rather than swallowing the error into an empty result -
        # a real, deliberate difference in behavior between the three.
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises/ex-1/fit",
            json={"error": "server_error"},
            status=500,
        )

        with self.assertRaises(HTTPError):
            _extractor().get_specifc_exercise_FIT_file(exerciseId="ex-1")


if __name__ == "__main__":
    unittest.main()

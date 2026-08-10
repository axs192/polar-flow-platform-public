import unittest
from unittest.mock import patch

from src.app.ETL.load_creator import load_creator
from src.data.loader import load_json


class TestCreateLoadOtherData(unittest.TestCase):
    """ """

    def setUp(self):
        self.incorrect_data = load_json("keys_missing_exercise.json")
        self.sample_data = load_json("other_data_sample.json")

    @patch("src.app.ETL.load_creator.config_loader")
    def test_givenCorrectData_thenHandledCorrectly(self, mock_config_loader):
        mock_config_loader.return_value = {"user_id": "user"}

        result = load_creator(response=self.sample_data).create_load()
        self.assertEqual(type(result), dict)
        self.assertEqual(len(result), 10)
        self.assertEqual(result.get("distance"), None)


if __name__ == "__main__":
    unittest.main()

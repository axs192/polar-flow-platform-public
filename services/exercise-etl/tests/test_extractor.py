import unittest
from unittest.mock import patch

from src.app.ETL.extractor import Extractor


class TestExtractorRunning(unittest.TestCase):
    """
    Class
    """

    def setUp(self):
        # Patch config_loader and AccessLink to avoid side effects
        self.extractor = Extractor.__new__(Extractor)
        self.extractor.config = {
            "access_token": "token",
            "client_id": "id",
            "client_secret": "secret",
            "user_id": "user",
        }

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_given_requestList_then_handledCorrectly(self, mock_accesslink, mock_config_loader):
        """
        This is mocking a non-200 code for exercises function, and expecting that a
        blank list is returned,and a log message is produced to say.
        """
        # Mock config_loader returns valid config
        mock_config_loader.return_value = self.extractor.config

        # Mock AccessLink instance and its activity method
        mock_listExercise = mock_accesslink.return_value.exercises.list_exercise
        mock_listExercise.return_value = [
            {
                "id": "2AC312F",
                "upload_time": "2008-10-13T10:40:02.000Z",
                "polar_user": "https://www.polaraccesslink/v3/users/1",
                "device": "Polar M400",
            },
            {
                "id": "2AC312F",
                "upload_time": "2008-10-13T10:40:02.000Z",
                "polar_user": "https://www.polaraccesslink/v3/users/1",
                "device": "Polar M400",
            },
        ]

        extractor = Extractor()
        result = extractor.get_exercises()
        self.assertEqual(len(result), 2)

    @patch("src.app.ETL.extractor.config_loader")
    @patch("src.app.ETL.extractor.AccessLink")
    def test_given_2requestSpecific_then_exercisehandledCorrectly(
        self, mock_accesslink, mock_config_loader
    ):
        """
        This is mocking a 200 code for the exercise function in extractor,
        and expecting that a dict is returned.
        """
        mock_config_loader.return_value = self.extractor.config

        # Mock AccessLink instance and its activity method

        mock_get_exercise = mock_accesslink.return_value.exercises.get_exercise
        mock_get_exercise.return_value = {
            "id": "2AC312F",
            "upload_time": "2008-10-13T10:40:02.000Z",
            "polar_user": "https://www.polaraccesslink/v3/users/1",
            "device": "Polar M400",
        }

        extractor = Extractor()
        result = extractor.get_specifc_exercise(exerciseId="asdccsas")
        self.assertEqual(len(result), 4)


if __name__ == "__main__":
    unittest.main()

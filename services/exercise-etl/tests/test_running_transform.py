import os
import unittest
from unittest.mock import patch

from src.app.ETL.transform import Transform
from src.data.loader import load_json


class TestTransform(unittest.TestCase):
    """ """

    def setUp(self):
        self.sample_exercise = load_json("sample_exercise.json")
        self.incorrect_data = load_json("keys_missing_exercise.json")
        self.sample_data = load_json("sample_data.json")

    def test_givenISOformat_thenConvertCorrectly(self):

        result = Transform(response=self.sample_data).calculate_duration()
        self.assertEqual(result, 8239.604)

    def test_givenNoDuration_thenReturnNone(self):
        # with self.assertRaises(TypeError):
        #     Transform(response=self.incorrect_data).calculate_duration()
        result = Transform(response=self.incorrect_data).calculate_duration()
        self.assertIsNone(result)

    def test_givenSampleKey_thenReturnDict(self):
        result = Transform(response=self.sample_data).helper_extractSample(sample_key=1)
        self.assertEqual(type(result), dict)

    def test_givenHeartSample_thenReturnDrift(self):
        result = Transform(response=self.sample_data).calculate_HRDrift()
        self.assertEqual(result, 4.41)

    def test_givenPaceSample_thenReturnDrift(self):
        result = Transform(response=self.sample_data).calculate_paceVariability()
        self.assertEqual(result, -4.24)

    def test_givenNoSample_thenReturnNone(self):
        result = Transform(response=self.incorrect_data).calculate_HRDrift()
        self.assertIsNone(result)

    def test_givenCorrectData_thenCalculateCardioDens(self):
        result = Transform(response=self.sample_data).calculate_loadDensity()
        self.assertEqual(result, 2.81)

    def test_incorrectData_thenCardioDensNone(self):
        result = Transform(response=self.incorrect_data).calculate_loadDensity()
        self.assertIsNone(result)

    def test_givenCorrectData_thenCalculateMeanPace(self):
        result = Transform(response=self.sample_data).calculate_meanPace()
        self.assertEqual(result, 11.54)

    def test_givenCorrectData_thenCalcEffFactor(self):
        result = Transform(response=self.sample_data).calculate_efficiencyFactor()
        self.assertEqual(result, 0.07745)

    def test_givenCorrectData_thenCalculateZones(self):
        result = Transform(response=self.sample_data).calculate_zones()
        self.assertEqual(type(result), dict)
        self.assertEqual(len(result), 5)
        self.assertEqual(result.get("Recovery"), 256)

    def test_givenCorrectData_thenCalculateMiles(self):
        result = Transform(response=self.sample_data).calculate_distanceMiles()
        self.assertEqual(result, 11.9)

    @patch("src.app.ETL.transform.load_fit_session_dataframe")
    def test_givenAltitude_thenCalulateElevGain(self, mock_load_fit_session):
        mock_load_fit_session.return_value = {"total_ascent": 400, "total_descent": 350}
        with patch.dict(os.environ, {"FIT_FILE": "session.fit"}):
            up, _down = Transform(response=self.sample_data).get_elevation_data()
        self.assertEqual(up, 1312)

    @patch("src.app.ETL.transform.load_fit_session_dataframe")
    def test_givenAltitude_thenCalulateElevDec(self, mock_load_fit_session):
        mock_load_fit_session.return_value = {"total_ascent": 400, "total_descent": 350}
        with patch.dict(os.environ, {"FIT_FILE": "session.fit"}):
            _up, down = Transform(response=self.sample_data).get_elevation_data()
        self.assertEqual(down, 1148)


if __name__ == "__main__":
    unittest.main()

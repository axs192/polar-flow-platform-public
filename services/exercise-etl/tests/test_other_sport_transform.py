import unittest

# from unittest.mock import patch
from src.app.ETL.transform import Transform
from src.data.loader import load_json


class TestTransformOtherSport(unittest.TestCase):
    """ """

    def setUp(self):
        self.incorrect_data = load_json("keys_missing_exercise.json")
        self.sample_data = load_json("other_data_sample.json")

    def test_givenISOformat_thenConvertCorrectly(self):

        result = Transform(response=self.sample_data).calculate_duration()
        self.assertEqual(result, 609.974)

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
        self.assertEqual(result, 1.06)

    def test_givenPaceSample_thenReturnDrift(self):
        result = Transform(response=self.sample_data).calculate_paceVariability()
        self.assertEqual(result, None)

    def test_givenNoSample_thenReturnNone(self):
        result = Transform(response=self.incorrect_data).calculate_HRDrift()
        self.assertIsNone(result)

    def test_givenCorrectData_thenCalculateCardioDens(self):
        result = Transform(response=self.sample_data).calculate_loadDensity()
        self.assertEqual(result, 0.83)

    def test_incorrectData_thenCardioDensNone(self):
        result = Transform(response=self.incorrect_data).calculate_loadDensity()
        self.assertIsNone(result)

    def test_givenCorrectData_thenCalculateMeanPace(self):
        result = Transform(response=self.sample_data).calculate_meanPace()
        self.assertEqual(result, None)

    def test_givenCorrectData_thenCalcEffFactor(self):
        result = Transform(response=self.sample_data).calculate_efficiencyFactor()
        self.assertEqual(result, None)

    def test_givenCorrectData_thenCalculateZones(self):
        result = Transform(response=self.sample_data).calculate_zones()
        self.assertEqual(type(result), dict)
        self.assertEqual(len(result), 5)
        self.assertEqual(result.get("Recovery"), 444.0)

    def test_givenNoDistance_thenReturnNone(self):
        result = Transform(response=self.sample_data).calculate_distanceMiles()
        self.assertEqual(result, None)


if __name__ == "__main__":
    unittest.main()

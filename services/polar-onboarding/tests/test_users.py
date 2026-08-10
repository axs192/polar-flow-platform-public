import unittest

import requests
import responses
from src.users import USERS_URL, register_user


class TestRegisterUser(unittest.TestCase):
    @responses.activate
    def test_given_200_response_then_returns_registered_user(self):
        responses.add(
            responses.POST,
            USERS_URL,
            json={"polar-user-id": 999, "member-id": "member-123"},
            status=200,
        )

        result = register_user(access_token="tok", member_id="member-123")

        self.assertEqual(result["member-id"], "member-123")
        sent_request = responses.calls[0].request
        self.assertEqual(sent_request.headers["Authorization"], "Bearer tok")
        self.assertEqual(sent_request.body.decode(), '{"member-id": "member-123"}')

    @responses.activate
    def test_given_409_already_registered_then_raises_http_error(self):
        responses.add(
            responses.POST,
            USERS_URL,
            json={"errors": [{"code": "USER_ALREADY_REGISTERED"}]},
            status=409,
        )

        with self.assertRaises(requests.HTTPError):
            register_user(access_token="tok", member_id="member-123")


if __name__ == "__main__":
    unittest.main()

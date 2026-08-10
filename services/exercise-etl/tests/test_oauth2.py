import unittest

import responses
from requests.exceptions import HTTPError
from src.app.accesslink.oauth2 import OAuth2Client

BASE_URL = "https://www.polaraccesslink.com/v3"
AUTHORIZATION_URL = "https://flow.polar.com/oauth2/authorization"
TOKEN_URL = "https://polarremote.com/v2/oauth2/token"


def _client(redirect_url=None):
    return OAuth2Client(
        url=BASE_URL,
        authorization_url=AUTHORIZATION_URL,
        access_token_url=TOKEN_URL,
        redirect_url=redirect_url,
        client_id="client-id",
        client_secret="client-secret",
    )


class TestAuthorizationUrl(unittest.TestCase):
    def test_omits_redirect_uri_when_none_configured(self):
        url = _client().get_authorization_url()

        self.assertIn("client_id=client-id", url)
        self.assertIn("response_type=code", url)
        self.assertNotIn("redirect_uri", url)
        self.assertTrue(url.startswith(AUTHORIZATION_URL + "?"))

    def test_includes_redirect_uri_when_configured(self):
        url = _client(redirect_url="https://example.com/callback").get_authorization_url()

        self.assertIn("redirect_uri=https%3A%2F%2Fexample.com%2Fcallback", url)


class TestAuthHeaders(unittest.TestCase):
    def test_bearer_header_shape(self):
        headers = _client().get_auth_headers("token-123")

        self.assertEqual(headers["Authorization"], "Bearer token-123")
        self.assertEqual(headers["Accept"], "application/json")


class TestGetAccessToken(unittest.TestCase):
    @responses.activate
    def test_success_returns_parsed_json_and_posts_expected_form_body(self):
        responses.add(
            responses.POST,
            TOKEN_URL,
            json={"access_token": "abc123", "token_type": "bearer"},
            status=200,
        )

        result = _client(redirect_url="https://example.com/callback").get_access_token(
            authorization_code="auth-code"
        )

        self.assertEqual(result, {"access_token": "abc123", "token_type": "bearer"})
        sent_body = responses.calls[0].request.body
        self.assertIn("grant_type=authorization_code", sent_body)
        self.assertIn("code=auth-code", sent_body)
        self.assertIn("redirect_uri=", sent_body)

    @responses.activate
    def test_error_response_raises_http_error(self):
        responses.add(
            responses.POST,
            TOKEN_URL,
            json={"error": "invalid_grant"},
            status=400,
        )

        with self.assertRaises(HTTPError):
            _client().get_access_token(authorization_code="bad-code")


class TestRequestDispatch(unittest.TestCase):
    @responses.activate
    def test_get_with_access_token_uses_bearer_auth_and_returns_json(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises",
            json={"exercises": []},
            status=200,
        )

        result = _client().get(endpoint="/exercises", access_token="token-123")

        self.assertEqual(result, {"exercises": []})
        self.assertEqual(
            responses.calls[0].request.headers["Authorization"], "Bearer token-123"
        )

    @responses.activate
    def test_no_access_token_falls_back_to_http_basic_auth(self):
        responses.add(responses.GET, f"{BASE_URL}/exercises", json={}, status=200)

        _client().get(endpoint="/exercises")

        # HTTPBasicAuth on the request produces a standard Authorization: Basic header,
        # not the Bearer header used when an access_token is supplied.
        auth_header = responses.calls[0].request.headers["Authorization"]
        self.assertTrue(auth_header.startswith("Basic "))

    @responses.activate
    def test_204_no_content_returns_empty_dict(self):
        responses.add(responses.DELETE, f"{BASE_URL}/users/1", status=204)

        result = _client().delete(endpoint="/users/1", access_token="token-123")

        self.assertEqual(result, {})

    @responses.activate
    def test_non_json_text_response_returns_raw_text(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises",
            body="plain text body",
            status=200,
            content_type="text/plain",
        )

        result = _client().get(endpoint="/exercises", access_token="token-123")

        self.assertEqual(result, "plain text body")

    @responses.activate
    def test_404_raises_http_error_with_status_and_body_in_message(self):
        responses.add(
            responses.GET,
            f"{BASE_URL}/exercises",
            json={"error": "not_found"},
            status=404,
        )

        with self.assertRaises(HTTPError) as ctx:
            _client().get(endpoint="/exercises", access_token="token-123")

        self.assertIn("404", str(ctx.exception))

    @responses.activate
    def test_post_and_put_dispatch_to_correct_http_methods(self):
        responses.add(responses.POST, f"{BASE_URL}/users", json={"id": 1}, status=201)
        responses.add(responses.PUT, f"{BASE_URL}/users/1", json={"id": 1}, status=200)

        post_result = _client().post(endpoint="/users", access_token="t", json={"member-id": "x"})
        put_result = _client().put(endpoint="/users/1", access_token="t")

        self.assertEqual(post_result, {"id": 1})
        self.assertEqual(put_result, {"id": 1})


if __name__ == "__main__":
    unittest.main()

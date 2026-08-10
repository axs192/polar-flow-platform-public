import unittest

import requests
import responses
from src.oauth import OAUTH_EXCHANGE_URL, build_authorize_url, exchange_code_for_token, extract_code


class TestBuildAuthorizeUrl(unittest.TestCase):
    def test_minimal(self):
        url = build_authorize_url(client_id="abc123")
        self.assertTrue(url.startswith("https://flow.polar.com/oauth2/authorization?"))
        self.assertIn("response_type=code", url)
        self.assertIn("client_id=abc123", url)

    def test_with_redirect_and_state(self):
        url = build_authorize_url(
            client_id="abc123", redirect_uri="https://example.com/cb", state="xyz"
        )
        self.assertIn("redirect_uri=https%3A%2F%2Fexample.com%2Fcb", url)
        self.assertIn("state=xyz", url)


class TestExtractCode(unittest.TestCase):
    def test_raw_code_passthrough(self):
        self.assertEqual(extract_code("  some-code-123  "), "some-code-123")

    def test_extract_from_full_redirect_url(self):
        url = "https://example.com/cb?code=abc-def&state=xyz"
        self.assertEqual(extract_code(url), "abc-def")

    def test_url_without_code_raises(self):
        with self.assertRaises(ValueError):
            extract_code("https://example.com/cb?state=xyz")


class TestExchangeCodeForToken(unittest.TestCase):
    @responses.activate
    def test_given_200_response_then_returns_parsed_token(self):
        responses.add(
            responses.POST,
            OAUTH_EXCHANGE_URL,
            json={
                "access_token": "tok",
                "token_type": "bearer",
                "expires_in": 3600,
                "x_user_id": 12345,
            },
            status=200,
        )

        result = exchange_code_for_token(
            client_id="cid",
            client_secret="csecret",
            code="the-code",
            redirect_uri="https://example.com/cb",
        )

        self.assertEqual(result["x_user_id"], 12345)
        self.assertEqual(len(responses.calls), 1)
        sent_request = responses.calls[0].request
        self.assertEqual(sent_request.headers["Authorization"][:6], "Basic ")
        sent_body = sent_request.body
        if isinstance(sent_body, bytes):
            sent_body = sent_body.decode()
        self.assertIn("grant_type=authorization_code", sent_body)
        self.assertIn("code=the-code", sent_body)
        self.assertIn("redirect_uri=https%3A%2F%2Fexample.com%2Fcb", sent_body)

    @responses.activate
    def test_given_401_response_then_raises_http_error(self):
        responses.add(
            responses.POST,
            OAUTH_EXCHANGE_URL,
            json={"error": "invalid_client"},
            status=401,
        )

        with self.assertRaises(requests.HTTPError):
            exchange_code_for_token(client_id="cid", client_secret="wrong-secret", code="the-code")


if __name__ == "__main__":
    unittest.main()

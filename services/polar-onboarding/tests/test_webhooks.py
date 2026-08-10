import unittest

import requests
import responses
from src.webhooks import WEBHOOKS_URL, create_webhook, delete_webhook, get_webhooks, update_webhook


class TestWebhooks(unittest.TestCase):
    @responses.activate
    def test_create_webhook_given_200_returns_signature_secret(self):
        responses.add(
            responses.POST,
            WEBHOOKS_URL,
            json={"data": {"signature_secret_key": "s3cr3t"}},
            status=200,
        )

        result = create_webhook(
            client_id="cid",
            client_secret="csecret",
            callback_url="https://example.com/webhook",
            events=["EXERCISE", "SLEEP"],
        )

        self.assertEqual(result["data"]["signature_secret_key"], "s3cr3t")
        sent_request = responses.calls[0].request
        self.assertEqual(
            sent_request.body.decode(),
            '{"events": ["EXERCISE", "SLEEP"], "url": "https://example.com/webhook"}',
        )
        self.assertTrue(sent_request.headers["Authorization"].startswith("Basic "))

    @responses.activate
    def test_create_webhook_given_409_then_raises_http_error(self):
        responses.add(
            responses.POST,
            WEBHOOKS_URL,
            json={"errors": [{"code": "DUPLICATE_WEBHOOK"}]},
            status=409,
        )

        with self.assertRaises(requests.HTTPError):
            create_webhook(
                client_id="cid",
                client_secret="csecret",
                callback_url="https://example.com/webhook",
                events=["EXERCISE"],
            )

    @responses.activate
    def test_update_webhook_sends_expected_body(self):
        responses.add(responses.PATCH, f"{WEBHOOKS_URL}/wh-1", json={"ok": True}, status=200)

        result = update_webhook(
            client_id="cid",
            client_secret="csecret",
            webhook_id="wh-1",
            callback_url="https://example.com/new",
            events=["EXERCISE"],
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(responses.calls[0].request.url, f"{WEBHOOKS_URL}/wh-1")
        self.assertIn('"url": "https://example.com/new"', responses.calls[0].request.body.decode())

    @responses.activate
    def test_get_webhooks(self):
        responses.add(responses.GET, WEBHOOKS_URL, json={"data": []}, status=200)

        result = get_webhooks(client_id="cid", client_secret="csecret")
        self.assertEqual(result, {"data": []})

    @responses.activate
    def test_delete_webhook_given_204_succeeds(self):
        responses.add(responses.DELETE, f"{WEBHOOKS_URL}/wh-1", status=204)

        delete_webhook(client_id="cid", client_secret="csecret", webhook_id="wh-1")

        self.assertEqual(responses.calls[0].request.url, f"{WEBHOOKS_URL}/wh-1")

    @responses.activate
    def test_delete_webhook_given_404_then_raises_http_error(self):
        responses.add(
            responses.DELETE,
            f"{WEBHOOKS_URL}/wh-1",
            json={"errors": [{"code": "NOT_FOUND"}]},
            status=404,
        )

        with self.assertRaises(requests.HTTPError):
            delete_webhook(client_id="cid", client_secret="csecret", webhook_id="wh-1")


if __name__ == "__main__":
    unittest.main()

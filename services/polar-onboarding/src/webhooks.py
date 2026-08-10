"""Polar webhook subscription management (POST/PATCH/GET /v3/webhooks).

Same request shape as the existing (working) create_webhook()/
update_webhook()/get_webhook() in health-sync, but as pure functions
returning the response - callers decide what to persist. The create
response includes signature_secret_key, which Polar's docs describe as
what's used to sign every webhook payload; the caller is responsible
for storing it (see secrets.py) - it was previously a manual step.
"""

import requests
from requests.auth import HTTPBasicAuth

WEBHOOKS_URL = "https://www.polaraccesslink.com/v3/webhooks"


def create_webhook(
    client_id: str, client_secret: str, callback_url: str, events: list[str]
) -> dict:
    """Create a new webhook subscription. Returns the response body,
    which includes signature_secret_key on success."""
    response = requests.post(
        WEBHOOKS_URL,
        auth=HTTPBasicAuth(client_id, client_secret),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json={"events": events, "url": callback_url},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def update_webhook(
    client_id: str, client_secret: str, webhook_id: str, callback_url: str, events: list[str]
) -> dict:
    """Update an existing webhook subscription's URL and/or events."""
    response = requests.patch(
        f"{WEBHOOKS_URL}/{webhook_id}",
        auth=HTTPBasicAuth(client_id, client_secret),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        json={"events": events, "url": callback_url},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def get_webhooks(client_id: str, client_secret: str) -> dict:
    """List the current webhook subscription(s)."""
    response = requests.get(
        WEBHOOKS_URL,
        auth=HTTPBasicAuth(client_id, client_secret),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def delete_webhook(client_id: str, client_secret: str, webhook_id: str) -> None:
    """Delete a webhook subscription. Nothing in the old codebase ever
    implemented this - added here since a real onboarding/offboarding tool
    needs it."""
    response = requests.delete(
        f"{WEBHOOKS_URL}/{webhook_id}",
        auth=HTTPBasicAuth(client_id, client_secret),
        timeout=30,
    )
    response.raise_for_status()

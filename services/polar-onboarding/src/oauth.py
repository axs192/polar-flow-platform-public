"""OAuth2 authorization-code flow against the Polar Accesslink API.

Endpoints and field names per Polar's Accesslink API docs (not just
reverse-engineered from old code): authorize at
https://flow.polar.com/oauth2/authorization, exchange at
https://polarremote.com/v2/oauth2/token.
"""

from urllib.parse import parse_qs, urlencode, urlparse

import requests

AUTHORIZE_URL = "https://flow.polar.com/oauth2/authorization"
OAUTH_EXCHANGE_URL = "https://polarremote.com/v2/oauth2/token"


def build_authorize_url(
    client_id: str, redirect_uri: str | None = None, state: str | None = None
) -> str:
    """Build the URL a human needs to open in a browser to authorize this app."""
    params = {"response_type": "code", "client_id": client_id}
    if redirect_uri:
        params["redirect_uri"] = redirect_uri
    if state:
        params["state"] = state
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def extract_code(pasted_value: str) -> str:
    """Accept either a raw authorization code or the full redirect URL the
    user was sent to after authorizing, and return just the code."""
    pasted_value = pasted_value.strip()
    if pasted_value.startswith("http"):
        query = parse_qs(urlparse(pasted_value).query)
        codes = query.get("code")
        if not codes:
            raise ValueError("No 'code' query parameter found in the pasted URL")
        return codes[0]
    return pasted_value


def exchange_code_for_token(
    client_id: str, client_secret: str, code: str, redirect_uri: str | None = None
) -> dict:
    """Exchange an authorization code for an access token.

    Returns a dict with access_token, token_type, expires_in, x_user_id
    (x_user_id is the Polar user id - what everywhere else in this repo
    calls user_id/uid).
    """
    data = {"grant_type": "authorization_code", "code": code}
    if redirect_uri:
        data["redirect_uri"] = redirect_uri

    response = requests.post(
        OAUTH_EXCHANGE_URL,
        auth=(client_id, client_secret),
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json;charset=UTF-8",
        },
        data=data,
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

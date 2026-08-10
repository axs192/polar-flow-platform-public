"""User registration against the Polar Accesslink API.

POST /v3/users per Polar's docs. Reuses the same request shape as the
existing (working) Users.register() in the exercise-etl service's
accesslink client.
"""

import requests

USERS_URL = "https://www.polaraccesslink.com/v3/users"


def register_user(access_token: str, member_id: str) -> dict:
    """Register a user after they've authorized this app.

    :param access_token: the user's access token from the OAuth exchange.
    :param member_id: a unique, partner-chosen identifier for the user.
    :return: the user object Polar returns (polar-user-id, member-id, etc.)
    """
    response = requests.post(
        USERS_URL,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        json={"member-id": member_id},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()

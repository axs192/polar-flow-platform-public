"""CLI for onboarding a Polar user and managing the webhook subscription.

Replaces what used to be manual, undocumented steps (an initial OAuth
authorization that nothing in the old codebase automated, plus a
signature_secret_key that had to be copied into Secrets Manager by hand).

--client-id/--client-secret fall back to the POLAR_CLIENT_ID/POLAR_CLIENT_SECRET
env vars (or a local .env file - see README.md) if omitted, so they don't
need to be retyped on every command.

Usage:
    python -m src.cli authorize --client-id <client_id> [--redirect-uri <uri>]
    python -m src.cli register --access-token <access_token> --member-id <member_id>
    python -m src.cli webhook create --client-id <client_id> --client-secret <client_secret> \
        --callback-url <url> --events EXERCISE,SLEEP \
        [--store-secret-name <name> --region <region> --aws-profile <profile>]
    python -m src.cli webhook update ...
    python -m src.cli webhook get --client-id <client_id> --client-secret <client_secret>
    python -m src.cli webhook delete --client-id <client_id> --client-secret <client_secret> --webhook-id <webhook_id>
"""

import argparse
import json
import os
import sys

from dotenv import load_dotenv

from src.oauth import build_authorize_url, exchange_code_for_token, extract_code
from src.secrets import set_secret_keys
from src.users import register_user
from src.webhooks import create_webhook, delete_webhook, get_webhooks, update_webhook

load_dotenv()


def _require(value, flag, env_var):
    """Fail clearly when a credential wasn't given as a flag or an env var/.env entry."""
    if not value:
        sys.exit(f"{flag} is required - pass it directly or set {env_var} (see README.md's .env option)")
    return value


def cmd_authorize(args):
    client_id = _require(args.client_id, "--client-id", "POLAR_CLIENT_ID")
    client_secret = _require(args.client_secret, "--client-secret", "POLAR_CLIENT_SECRET")
    url = build_authorize_url(client_id, redirect_uri=args.redirect_uri, state=args.state)
    print(f"Open this URL in a browser, authorize the app, and you'll be redirected:\n\n{url}\n")
    pasted = input("Paste the code, or the full redirect URL you landed on: ")
    code = extract_code(pasted)

    token_response = exchange_code_for_token(
        client_id=client_id,
        client_secret=client_secret,
        code=code,
        redirect_uri=args.redirect_uri,
    )
    print(json.dumps(token_response, indent=2))
    print(
        "\nSave access_token and x_user_id yourself - this tool does not "
        "write them anywhere automatically."
    )


def cmd_register(args):
    result = register_user(access_token=args.access_token, member_id=args.member_id)
    print(json.dumps(result, indent=2))


def cmd_webhook_create(args):
    client_id = _require(args.client_id, "--client-id", "POLAR_CLIENT_ID")
    client_secret = _require(args.client_secret, "--client-secret", "POLAR_CLIENT_SECRET")
    result = create_webhook(
        client_id=client_id,
        client_secret=client_secret,
        callback_url=args.callback_url,
        events=args.events.split(","),
    )
    print(json.dumps(result, indent=2))
    _maybe_store_signature_secret(args, result)


def cmd_webhook_update(args):
    client_id = _require(args.client_id, "--client-id", "POLAR_CLIENT_ID")
    client_secret = _require(args.client_secret, "--client-secret", "POLAR_CLIENT_SECRET")
    result = update_webhook(
        client_id=client_id,
        client_secret=client_secret,
        webhook_id=args.webhook_id,
        callback_url=args.callback_url,
        events=args.events.split(","),
    )
    print(json.dumps(result, indent=2))


def cmd_webhook_get(args):
    client_id = _require(args.client_id, "--client-id", "POLAR_CLIENT_ID")
    client_secret = _require(args.client_secret, "--client-secret", "POLAR_CLIENT_SECRET")
    print(json.dumps(get_webhooks(client_id, client_secret), indent=2))


def cmd_webhook_delete(args):
    client_id = _require(args.client_id, "--client-id", "POLAR_CLIENT_ID")
    client_secret = _require(args.client_secret, "--client-secret", "POLAR_CLIENT_SECRET")
    delete_webhook(client_id, client_secret, args.webhook_id)
    print("Deleted.")


def _maybe_store_signature_secret(args, create_response):
    if not args.store_secret_name:
        print(
            "\n--store-secret-name not given - signature_secret_key above "
            "was not saved anywhere. Store it in Secrets Manager yourself."
        )
        return
    secret_key = create_response.get("data", {}).get("signature_secret_key")
    if not secret_key:
        print(
            "\nWarning: no signature_secret_key in the response - nothing to store.",
            file=sys.stderr,
        )
        return
    set_secret_keys(
        args.store_secret_name,
        args.region,
        {"POLAR_WEBHOOK": secret_key},
        profile_name=args.aws_profile,
    )
    print(f"\nStored signature_secret_key as POLAR_WEBHOOK in secret '{args.store_secret_name}'.")


def build_parser():
    parser = argparse.ArgumentParser(prog="polar-onboarding")
    subparsers = parser.add_subparsers(dest="command", required=True)

    authorize_p = subparsers.add_parser("authorize", help="Run the OAuth2 authorization-code flow")
    authorize_p.add_argument("--client-id", default=os.environ.get("POLAR_CLIENT_ID"))
    authorize_p.add_argument("--client-secret", default=os.environ.get("POLAR_CLIENT_SECRET"))
    authorize_p.add_argument("--redirect-uri")
    authorize_p.add_argument("--state")
    authorize_p.set_defaults(func=cmd_authorize)

    register_p = subparsers.add_parser("register", help="Register a user (POST /v3/users)")
    register_p.add_argument("--access-token", required=True)
    register_p.add_argument("--member-id", required=True)
    register_p.set_defaults(func=cmd_register)

    webhook_p = subparsers.add_parser("webhook", help="Manage the webhook subscription")
    webhook_sub = webhook_p.add_subparsers(dest="webhook_command", required=True)

    create_p = webhook_sub.add_parser("create")
    create_p.add_argument("--client-id", default=os.environ.get("POLAR_CLIENT_ID"))
    create_p.add_argument("--client-secret", default=os.environ.get("POLAR_CLIENT_SECRET"))
    create_p.add_argument("--callback-url", required=True)
    create_p.add_argument("--events", required=True, help="Comma-separated, e.g. EXERCISE,SLEEP")
    create_p.add_argument("--store-secret-name", help="If given, store signature_secret_key here")
    create_p.add_argument("--region", default="us-east-1")
    create_p.add_argument(
        "--aws-profile",
        default=os.environ.get("AWS_PROFILE"),
        help="AWS CLI profile to use when writing --store-secret-name (e.g. polar-app-prod). "
        "Defaults to boto3's normal credential resolution if omitted, which is NOT this "
        "account unless AWS_PROFILE is already set - see terraform/environments/prod/README.md.",
    )
    create_p.set_defaults(func=cmd_webhook_create)

    update_p = webhook_sub.add_parser("update")
    update_p.add_argument("--client-id", default=os.environ.get("POLAR_CLIENT_ID"))
    update_p.add_argument("--client-secret", default=os.environ.get("POLAR_CLIENT_SECRET"))
    update_p.add_argument("--webhook-id", required=True)
    update_p.add_argument("--callback-url", required=True)
    update_p.add_argument("--events", required=True)
    update_p.set_defaults(func=cmd_webhook_update)

    get_p = webhook_sub.add_parser("get")
    get_p.add_argument("--client-id", default=os.environ.get("POLAR_CLIENT_ID"))
    get_p.add_argument("--client-secret", default=os.environ.get("POLAR_CLIENT_SECRET"))
    get_p.set_defaults(func=cmd_webhook_get)

    delete_p = webhook_sub.add_parser("delete")
    delete_p.add_argument("--client-id", default=os.environ.get("POLAR_CLIENT_ID"))
    delete_p.add_argument("--client-secret", default=os.environ.get("POLAR_CLIENT_SECRET"))
    delete_p.add_argument("--webhook-id", required=True)
    delete_p.set_defaults(func=cmd_webhook_delete)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

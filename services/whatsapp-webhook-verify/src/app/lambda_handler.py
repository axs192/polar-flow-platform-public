from .config_loader import config_loader


def lambda_handler(event, context):
    """WhatsApp webhook verification handshake (GET).

    Meta calls this with hub.mode/hub.verify_token/hub.challenge when the
    webhook subscription is created or re-verified.
    """
    # queryStringParameters can be explicitly null in the event (not just
    # absent) when there's no query string - .get(..., {}) only covers the
    # "absent" case, so this defends against the None case too. Fixed here;
    # the deployed version this was recovered from would raise on that path.
    params = event.get("queryStringParameters") or {}
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    config = config_loader()
    # .get(), not config["META_VERIFY_TOKEN"]: the shared secret's value is
    # always populated by hand, out-of-band from Terraform - nothing
    # guarantees this specific key exists yet at invocation time, so a
    # verification attempt against an incompletely-populated secret must
    # fail as a clean 403, not crash on a KeyError.
    verify_token = config.get("META_VERIFY_TOKEN")

    if mode == "subscribe" and token == verify_token:
        return {"statusCode": 200, "body": challenge}

    return {"statusCode": 403, "body": "Forbidden"}

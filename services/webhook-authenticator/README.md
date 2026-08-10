# webhook-authenticator

Was `polar_authenticator`. The webhook ingress: receives the Polar Flow webhook at `POST /webhook`, verifies the HMAC signature, and dispatches to SQS based on event type (`SLEEP` → `polar-webhook.fifo`, `EXERCISE` → `exercise-message.fifo`; anything else is accepted and silently dropped). See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

Everything lives in `src/app/lambda_handler.py` (a single file, no sub-modules):

- Reads the `Polar-Webhook-Signature` header (case-insensitive lookup) — a **raw hex HMAC-SHA256 digest of the raw request body**, keyed with the `POLAR_WEBHOOK` secret. No `sha256=`-style prefix, unlike some webhook conventions — `verify_polar_signature()` computes `hmac.new(secret, raw_body, sha256).hexdigest()` and compares directly.
- Verifies that signature **before** parsing the body as JSON at all (a deliberate fix — the deployed code this was recovered from parsed first).
- Once verified, reads the body's `event` field: `SLEEP` → `send_message_to_sqs()` (queue URL from `SQS_QUEUE_URL`, message body is the literal string `"Process Daily Update"`, not the real payload); `EXERCISE` → `send_message_to_exercise_load_sqs()` (queue URL from `SQS_EXERCISE_QUEUE_URL`, forwards the full raw body). Any other `event` value falls through both `if`s and returns 200 with nothing dispatched.
- `config_loader.py` reads `POLAR_WEBHOOK` from the shared secret (`AWS_APP_SECRET_NAME` env var).

**This is not the local `webhook_authenticator` folder** — that folder didn't match what's actually deployed (different structure, a broken SSM lookup, dead DynamoDB code) and was dropped entirely. This service's code was recovered directly from the deployed Lambda zip and is the real starting point.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `ruff`/`bandit` clean; all 7 tests pass (moto-mocked SQS, no `.env` or real AWS needed). No Dockerfile needed (this stays a zip-deployed Lambda, not a container). Coverage 93%, gated in CI at 90%.

**Real fix applied**: the deployed code parsed the JSON webhook body (and read `body_dict["url"]`) *before* verifying the HMAC signature. Reordered so signature verification happens first — untrusted input shouldn't be touched until its authenticity is confirmed.

**Test coverage added**: the original had none that actually worked (the local folder's test used a broken SSM setup and was never verified to pass; the deployed code had no tests at all). `tests/test_lambda_handler.py` uses `moto` to mock Secrets Manager and SQS, and actually verifies: missing-signature → 400, invalid-signature → rejected, `SLEEP`/`EXERCISE` events dispatch to the correct queue, and other event types are accepted without dispatching (documenting today's real behavior, not necessarily its ideal behavior — see Known Issues in the architecture doc). Verified passing via `python -m unittest discover -s tests -t .` in a throwaway venv before committing.

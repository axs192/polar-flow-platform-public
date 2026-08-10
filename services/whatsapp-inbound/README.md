# whatsapp-inbound

Was `MetaResponse`. Receives inbound WhatsApp messages at `POST /messenger`, verifies the Meta `X-Hub-Signature-256` HMAC, extracts the message text, and forwards it to SQS for `exercise-insights` to answer. See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

Everything lives in `src/app/lambda_handler.py`:

- Reads the `X-Hub-Signature-256` header, strips Meta's `sha256=` prefix if present, and verifies it as a hex HMAC-SHA256 of the raw body keyed with `META_NOT_SEC` — note this **does** have the `sha256=` prefix, unlike `webhook-authenticator`'s Polar signature header, which doesn't.
- `extract_message_text()` walks Meta's nested webhook payload shape (`entry[0].changes[0].value.messages[0].text.body`) to pull out the actual message text, returning `None` (nothing forwarded, still 200s) if that path isn't present — e.g. delivery-status callbacks, which Meta also POSTs to the same URL.
- On a real message, `send_message_sqs()` forwards it to `SQS_USER_QUERY_QUEUE_URL` (the `user-query.fifo` queue `exercise-insights` consumes).
- `config_loader.py` reads `META_NOT_SEC` from the shared secret, called per-invocation (not at import time) so importing this module never makes a live Secrets Manager call as a side effect.

**No local source existed for this at all** — recovered directly from the deployed Lambda zip.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `ruff`/`bandit` clean; all 4 tests pass offline (moto-mocked SQS). No Dockerfile needed (zip-deployed). Coverage 89%, gated in CI at 85%.

**Real fixes applied**:
- **The misnamed queue env var** (flagged back in initial discovery): the deployed code read `SQS_EXERCISE_QUEUE_URL` — a copy-paste leftover from `webhook-authenticator` — but the value it actually held was the `PolarUserResponseAI.fifo` URL, nothing to do with exercise data. Renamed to `SQS_USER_QUERY_QUEUE_URL`, which is what it actually is. This is a **new required env var name** — Terraform/deployment needs to use this name going forward, not the old one.
- `config_loader()` moves from a module-level call (executed as a side effect of merely *importing* the file, before the deployed version's original code even ran) into the handler function, matching the pattern in `webhook-authenticator` and `whatsapp-webhook-verify`.
- The signature-verify-before-parse ordering was already correct in the original deployed code here (unlike `webhook-authenticator`) — no change needed on that front.

**Test coverage added**: none existed before (no local source at all). `tests/test_lambda_handler.py` uses `moto` for Secrets Manager and SQS, verifying missing/invalid signature handling, that a valid inbound message's text gets forwarded to the (renamed) queue, and that a payload with no message text doesn't forward anything. Verified passing via `python -m unittest discover -s tests -t .` in a throwaway venv before committing.

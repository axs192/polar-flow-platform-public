# whatsapp-webhook-verify

Was `MetaAuth`. Implements Meta's WhatsApp webhook verification handshake (GET, `hub.mode`/`hub.verify_token`/`hub.challenge`). See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

The entire service is `src/app/lambda_handler.py` — no sub-modules. Meta calls `GET /messenger` with `hub.mode`, `hub.verify_token`, `hub.challenge` as query parameters whenever a webhook subscription is created or re-verified (see `terraform/environments/prod/README.md`'s "Set up Meta/WhatsApp" section for triggering this for real). If `hub.mode == "subscribe"` and `hub.verify_token` matches the shared secret's `META_VERIFY_TOKEN` (a value you pick yourself when subscribing — see that same README section), it echoes `hub.challenge` back with a 200; otherwise 403. `config_loader.py` reads `META_VERIFY_TOKEN` from the shared secret.

**No local source existed for this at all** — recovered directly from the deployed Lambda zip. In the old account it's also currently **orphaned**: no API Gateway route is wired to it (no GET method exists anywhere), so it isn't reachable. Wiring it to a real route is part of the Terraform work later in this migration.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `ruff`/`bandit` clean; all 5 tests pass offline. No Dockerfile needed (zip-deployed). Coverage 93%, gated in CI at 90%.

**Real fixes applied**:
- `VERIFY_TOKEN` moves into Secrets Manager (key `META_VERIFY_TOKEN`) instead of a plaintext Lambda environment variable — consistent with every other credential in this system.
- `event.get('queryStringParameters', {})` only supplies the default when the key is *absent* — API Gateway's proxy integration can send it as an explicit `null` (present, but `None`) when there's no query string, which would have raised `AttributeError` on `.get()`. Fixed to `event.get('queryStringParameters') or {}`, and covered by a regression test.

**Test coverage added**: none existed before (no local source at all). `tests/test_lambda_handler.py` uses `moto` for Secrets Manager, verifies the correct-token/wrong-token paths, and specifically regression-tests both the null and the missing `queryStringParameters` cases. Verified passing via `python -m unittest discover -s tests -t .` in a throwaway venv before committing.

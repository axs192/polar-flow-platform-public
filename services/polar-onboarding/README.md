# polar-onboarding

**New code, not a migration.** A CLI for the steps that used to be manual and undocumented: authorizing a Polar user (OAuth2), registering them, and creating/updating the webhook subscription — including capturing the `signature_secret_key` Polar returns and writing it into Secrets Manager, instead of that being a copy-paste-by-hand step.

This is also the tool used for the old→new account cutover later in this migration: `webhook update` re-points the subscription's callback URL at the new account's API Gateway.

Grounded in Polar's actual Accesslink API docs (fetched during planning, not just inferred from the old code):
- Authorize: `GET https://flow.polar.com/oauth2/authorization` (`response_type=code`, `client_id`, optional `redirect_uri`/`scope`/`state`)
- Token exchange: `POST https://polarremote.com/v2/oauth2/token` (Basic auth, form-encoded `grant_type=authorization_code`) → returns `access_token`, `x_user_id` (this is the Polar user id every other service calls `user_id`/`uid`)
- Register: `POST /v3/users` with `{"member-id": ...}`
- Webhook create/update/get/delete: `/v3/webhooks[/{id}]`, partner-level HTTP Basic auth (`client_id`/`client_secret`, not a user token) — same shape as the existing, working code in `health-sync`. The create response's `signature_secret_key` is what every webhook payload is signed with.
- Webhook signing: header `Polar-Webhook-Signature`, HMAC-SHA256 — matches what `webhook-authenticator` already verifies.

## How this works

Not deployed — a local CLI, run by hand. Module breakdown:

- **`cli.py`** — the `argparse` wrapper; one subcommand per operation (`authorize`, `register`, `webhook create/update/get/delete`), each a thin `cmd_*` function that calls into the modules below and prints the result.
- **`oauth.py`** — `build_authorize_url()` builds the browser URL; `exchange_code_for_token()` does the code-for-token POST; `extract_code()` parses either a bare code or a full redirect URL pasted back.
- **`users.py`** — `register_user()`, the `POST /v3/users` call.
- **`webhooks.py`** — `create_webhook()`/`update_webhook()`/`get_webhooks()`/`delete_webhook()`, the `/v3/webhooks` CRUD set.
- **`secrets.py`** — `get_secret_dict()`/`set_secret_keys()`, a read-modify-write helper against Secrets Manager; `webhook create --store-secret-name` uses this to write `signature_secret_key` in as `POLAR_WEBHOOK` without clobbering the secret's other keys.

## Usage

`<...>` below marks a placeholder — substitute your own real value, don't type it literally.

```sh
# 1. Authorize a user (opens a browser flow manually, pastes the code back)
uv run python -m src.cli authorize --client-id <client_id> --client-secret <client_secret>

# 2. Register them
uv run python -m src.cli register --access-token <access_token> --member-id some-id

# 3. Create the webhook subscription, storing signature_secret_key automatically
uv run python -m src.cli webhook create --client-id <client_id> --client-secret <client_secret> \
    --callback-url https://.../webhook --events EXERCISE,SLEEP \
    --store-secret-name polar-app-prod/app-secrets --region us-east-1 \
    --aws-profile polar-app-prod
```

`--aws-profile` (or the `AWS_PROFILE` env var) controls which AWS CLI profile `--store-secret-name` writes with. Without it, this falls back to boto3's normal default-credential resolution — which, per this repo's convention (see root `CLAUDE.md`), is **not** `polar-app-prod` unless `AWS_PROFILE` is already set in your shell. This didn't turn out to be the cause of the one real incident so far (that was a separate response-parsing bug, now fixed), but it's a real, unrelated gap worth closing regardless — omitting it risks silently writing to (or failing against) the wrong account. Always pass it explicitly.

(`uv run` picks up this service's own `.venv` automatically — see `uv sync` in `terraform/environments/prod/README.md`'s "Onboard a real Polar user" section for the real, end-to-end walkthrough with real account values filled in.)

### Avoid retyping `--client-id`/`--client-secret` on every command

Every subcommand above falls back to the `POLAR_CLIENT_ID`/`POLAR_CLIENT_SECRET`
env vars when the flag is omitted (an explicit flag always overrides the env
var). The simplest way to set these once: create a `.env` file in this
directory (already covered by the repo-wide `.gitignore` — never committed)
containing

```
POLAR_CLIENT_ID=<client_id>
POLAR_CLIENT_SECRET=<client_secret>
```

`cli.py` loads it automatically via `python-dotenv`. If neither the flag nor
the env var is set, the command exits with a clear error naming both options
instead of an opaque argparse "required" failure.

`AWS_PROFILE=polar-app-prod` works the same way in the same `.env` file, as
a default for `webhook create --store-secret-name`'s `--aws-profile` flag —
see `terraform/environments/prod/README.md` for why this matters (it's not
automatic just because other `aws` CLI calls elsewhere in this repo already
use that profile).

No local HTTP server/redirect listener — `authorize` prints the URL, you open it, authorize, and paste back either the raw code or the full URL you land on afterward.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); not yet integrated into Terraform/CI. `ruff`/`bandit` clean. All 40 tests (`tests/`) pass offline: the Polar HTTP calls (`oauth.py`, `users.py`, `webhooks.py`) are tested with `responses` against real status codes and example response payloads — including the error paths (401/404/409), so `raise_for_status()` is actually exercised, not just asserted as "called" — and `moto` covers the Secrets Manager helper. `cli.py` (the argparse wrapper around all of the above) now has its own dedicated tests too: argument wiring for every subcommand, each `cmd_*` handler's stdout/stderr output, and the `--store-secret-name` branching in `webhook create` (present-and-stores, absent-and-warns, present-but-missing-key-and-warns-on-stderr, `--aws-profile`/`AWS_PROFILE` threading). Coverage 98%, gated in CI at 95%.

**Known limitation**: `webhook delete` didn't exist anywhere in the old codebase at all (no de-registration path). Added here since a real onboarding tool needs an offboarding path too, but it's untested against the real API (no local/sandbox Polar account available during this migration to verify against) — the request shape follows the same pattern as create/update/get, which are known-working.

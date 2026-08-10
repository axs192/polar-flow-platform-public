# health-sync

Was `sms_activties` / local folder `sms_activities`. Triggered by SQS `polar-webhook.fifo` (fires whenever a `SLEEP` webhook event arrives, not on a schedule despite the old naming): sends a WhatsApp activity summary, and backfills up to 10 days of health data to S3 + DynamoDB. See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

`main.lambda_handler` calls `run_app()`, which runs two sequential steps via `helpers/daily_helper.py`'s `Daily_Helper` — **upload first, notification last, deliberately** (as of 2026-08-07):

- **`upload_daily_load()`** — backfills up to 10 days via `ETL/extractor.py`'s `Extractor`, shapes it with `ETL/transform.py`, writes to the `health_metrics` table via `ETL/dynamo.py`'s `Health_Record`, and writes the same data to S3 (`BUCKET_NAME`/`FOLDER_PATH` env vars). Runs first because it's a keyed overwrite (`uid`+`date`) — safe and idempotent to retry, and its backfill loop resumes from wherever a prior attempt left off (via `get_latest_date()`), so a retry never duplicates data.
- **`send_daily_notification()`** — pulls recent activity via the same `Extractor`/`HealthData`, builds the message text via `messaging/create_message.py` + `response_templates.py` (daily/weekly comparison templates), and sends it over the WhatsApp Graph API via `messaging/push_notifications.py`. Runs last because it's the terminal, non-idempotent step: a message is only deleted from its SQS queue (no retry) once the notification has actually sent, so a successful notification is never re-sent — but a failure here raises and retries the whole thing on the next attempt (harmlessly re-running the idempotent upload first).

Every stage across both steps now raises on a real failure instead of swallowing it — a failure used to be logged and turned into a normal-looking return value, which meant the Lambda always reported success to SQS regardless of whether anything actually worked, so a real failure was silently deleted instead of retried/DLQ'd. See `docs/architecture.md`'s step 7 revision note for the incident that surfaced this.

`messaging/push_notifications.py` reads `TO_MOBILE`/`FROM_MOBILE` as plain Lambda environment variables (not Secrets Manager keys) — the WhatsApp Graph API send-token itself (`META_AUTH`) does come from the shared secret via `helpers/config_loader.py`, same as every other credential here.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `Dockerfile` is a multi-stage build, built and its `lambda_handler` entrypoint verified to import inside the resulting container. `ruff`/`bandit` clean; all 92 tests pass offline (moto for DynamoDB/S3, `responses` for the WhatsApp Graph API and Accesslink calls, `freezegun` for date logic) with no `.env` or real AWS resources required. Coverage 83%, gated in CI at 80%.

**Real bugs found and fixed closing the coverage gap on `main.py`/`oauth2.py`/`config_loader.py`/`extractor.py`** (previously the least-tested code in the service, including the `lambda_handler` entrypoint itself at 0%):
- `main.py` had the identical `logging.error("...: %e", e)` bug as `exercise-etl` in two places (`send_daily_notification`/`upload_daily_load` failure handlers) — `%e` against a caught exception made the logging call itself raise, swallowing the real error. Fixed to `%s` in both.
- `extractor.py`'s `__get_dates`/`get_physical_info` each had an inline `except` handler that logged a warning referencing a local variable (`to_date`/`date`) *before that variable was ever assigned* — raising `UnboundLocalError` instead of the intended warning-and-fallback. Fixed to reference `kwargs["to_date"]`/`kwargs["date"]` instead.
- Once that was fixed, a second bug surfaced underneath it: `get_physical_info`'s fallback set `date = datetime.now()` (a raw `datetime` object) instead of formatting it the same way every other branch does (`"%Y/%m/%d"`, a string) — breaking the DynamoDB string-keyed lookup that consumes it. Fixed to format consistently.

**Not carried over, deliberately:**
- `config.yml` — contained a **real personal phone number** (the actual WhatsApp recipient), in a stale Twilio-sandbox format the deployed code doesn't even use anymore (production reads `TO_MOBILE`/`FROM_MOBILE` as plain Lambda environment variables — see "How this works" above — not from this file). Not something to put in git history.
- `display_hr.py` — a local matplotlib plotting script, not part of the deployed Lambda path (`main.py` doesn't import it). Easy to rewrite later if wanted.
- `deploy.sh` / `integrate.sh` / `integration_test.sh` — hardcode the old account's real ECR repo name and API Gateway URL; CI/CD replaces these anyway.
- `src/app/webhooks/webhook.py` — the manual, one-off script that used to be run by hand to create/update the Polar webhook subscription (module-level side effects, no timeout on its HTTP calls, no tests). This workflow now lives in [`polar-onboarding`](../polar-onboarding/), which covers the same create/update/get behavior plus the delete path this script never had.
- The old `README.md` (described Twilio SMS, which doesn't match what's actually deployed — see Known Issues in the architecture doc).

**PII fix applied**: the real Polar user ID (not repeated here, for the same reason it's not repeated anywhere else in this repo) appeared in one JSON fixture (`src/data/files/health_extraction.json`) and directly in `tests/test_dailyhelper.py` (as an arbitrary test input, not tied to a specific expected result) — both replaced with a placeholder (`00000001`) before committing.

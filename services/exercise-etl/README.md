# exercise-etl

Was `polar_exercise_upload` / local folder `polar-exercise`. SQS-triggered (from `exercise-message.fifo`): fetches exercise JSON + `.fit` binary from Polar Accesslink, computes derived metrics (HR zones, drift, efficiency factor, pace, elevation), writes to DynamoDB `exercise_data`. See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

`main.lambda_handler` is the entry point: it pulls the SQS message body, reads its `entity_id` (the Polar exercise ID), and calls `run_app(exerciseId)`, which drives the rest.

- **`accesslink/`** — a small client for Polar's Accesslink API: `oauth2.py` handles the OAuth2 token exchange, `accesslink.py` wraps the REST endpoints (`endpoints/exercises.py`, `heart_rate.py`, etc.).
- **`ETL/extractor.py`** — `Extractor.get_specifc_exercise()` fetches the exercise JSON for one exercise ID; `get_specifc_exercise_FIT_file()` fetches the accompanying `.fit` binary.
- **`helpers/fit_file_helper.py`** — parses the `.fit` binary (via `fitparse`) into a normalized session dataframe (per-record heart rate, pace, elevation, etc.).
- **`ETL/transform.py`** — `Transform` computes the derived metrics (HR zones, drift, efficiency factor, pace, elevation) from the raw exercise JSON + the parsed `.fit` data.
- **`ETL/load_creator.py`** — `load_creator` shapes the transformed data into the final DynamoDB item.
- **`ETL/load.py`** — `loader` writes that item to the `exercise_data` table (env var `TABLE_NAME`).
- **`helpers/config_loader.py`** — reads the shared secret (env var `AWS_APP_SECRET_NAME`) from Secrets Manager once per cold start and caches it module-level; this is where `access_token`/`client_id`/`client_secret` come from.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `Dockerfile` is a multi-stage build (`uv export` + install into a scratch target, copied into a plain Lambda base image) — built and its `lambda_handler` entrypoint verified to import inside the resulting container. `ruff`/`bandit` clean; all 65 tests pass offline (moto for DynamoDB, `responses` for the real Accesslink HTTP calls, no `.env` or real AWS needed). Coverage 82%, gated in CI at 80%.

**Note**: `src/data/files/` sample fixtures had the real Polar user ID scrubbed (replaced with `00000001`) before being committed — no test depends on the literal value. The real `.fit` binary fixture that used to sit here was dropped entirely (unused by any test, and it's real GPS track data from an actual run — not something to carry into a git history).

**Real fixes made closing the coverage gap on `main.py`/`oauth2.py`/`config_loader.py`/`extractor.py`** (previously the least-tested code in the service, including the `lambda_handler` entrypoint itself at 0%):
- `main.py`'s upload-failure handler logged `logging.error("...: %e", e)` against a caught exception — `%e` is a floating-point format spec, not a general one, so the logging call itself raised and the real error got swallowed by logging's own internal error handler instead of ever being logged. Fixed to `%s`.

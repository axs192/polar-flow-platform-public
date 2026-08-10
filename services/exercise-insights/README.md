# exercise-insights

Was `polar_query_response` / local folder `polar-response-ai`. Answers questions about the user's exercise history via an LLM. WhatsApp was a proof of concept — per the migration decision, this service now splits into `exercise_insights/core/` (transport-agnostic) and `exercise_insights/whatsapp_adapter/` (today's transport). See [docs/architecture.md](../../docs/architecture.md) for the full picture.

## How this works

SQS-triggered (`user-query.fifo`): `whatsapp_adapter/lambda_handler.py` → `event_handler.py`'s `extract_sqs_message()` pulls the question text out of the SQS message → `core/answer.py`'s `answer_question(user_id, question)` → `whatsapp_adapter/push_notification.py` sends the reply back over WhatsApp. `user_id` comes from the `POLAR_USER_ID` env var (set in `whatsapp_adapter/lambda_handler.py`, not inside `core/` — see below).

- **`exercise_insights/core/`** — transport-agnostic Q&A logic, no AWS-transport awareness at all (no SQS parsing, no WhatsApp sending) — the seam a future webserver integration calls into directly:
  - `answer.py` — `answer_question(user_id, question) -> str`: the orchestration itself.
  - `extract.py` — `dynamo_extract` reads the last 90 days of DynamoDB `exercise_data` for that user.
  - `transform/exercise.py`, `transform/health.py` — shape the raw records into summarized trends (load, HR, sleep, etc.) the prompt actually uses.
  - `prompts_loader.py` — loads the system prompt text from S3 (`BUCKET_NAME`/`EXERCISE_PROMPT_PATH`/`HEALTH_PROMPT_PATH` env vars).
  - `answer.py` then calls OpenAI directly (`OPEN_AI_AUTH` from the shared secret) to generate the reply.
- **`exercise_insights/whatsapp_adapter/`** — today's SQS-triggered Lambda: `lambda_handler.py` is the entry point, `event_handler.py` extracts the question text from the SQS event, `push_notification.py` sends `answer_question()`'s result back over the WhatsApp Graph API (`META_AUTH` from the shared secret, `TO_MOBILE`/`FROM_MOBILE` as plain env vars).
- **`exercise_insights/shared/`** — `config_loader`/`logging_config`, used by both.

**Status**: standardized on `uv` (`pyproject.toml` + `uv.lock`); `Dockerfile` is a multi-stage build, built and its `lambda_handler` entrypoint verified to import inside the resulting container. `ruff`/`bandit` clean. All 45 tests pass offline: `moto` for S3, `responses` for the WhatsApp Graph API call, `respx` for the OpenAI SDK's real HTTP wire format (not a mocked SDK client — a hand-built example `Response` JSON body validated against `openai`'s own type definitions). Coverage 78%, gated in CI at 75%.

**Real fixes made during the split** (not just relocation):
- The hardcoded real Polar user ID that used to live inside the Q&A logic itself is gone (not repeated here either, for the same reason it was scrubbed from the fixtures below). `answer_question` now takes `user_id` as a parameter; the WhatsApp-conversation → Polar-user mapping (still one fixed user today) lives explicitly in `whatsapp_adapter/lambda_handler.py` via a `POLAR_USER_ID` env var — a new required env var for this service going forward.
- Dropped dead code: `Event_Handler.extract_message_text` (a duplicate of `whatsapp-inbound`'s Meta-payload parsing that was never actually called here — this Lambda only ever receives SQS events) and `utils/validators.py`'s `Validator` class (an unused, unreferenced alternate implementation of the same webhook-signature check that properly lives in `whatsapp-inbound`).
- `logging_config.py`'s local log-file path used `Path(__file__).parents[3]`, correct for the old `src/app/utils/` depth (3 levels below the project root) but wrong after moving to `exercise_insights/shared/` (2 levels below the service root) — fixed to `parents[2]`. Only matters for local/non-Lambda runs; Lambda always uses stdout.
- `dotenv (>=0.9.9)` in the old `pyproject.toml` was actually the wrong PyPI package name for what the code imports (`from dotenv import load_dotenv`, which is `python-dotenv`) — corrected in `requirements.txt`.
- The real Polar user ID also appeared in three JSON test fixtures (`tests/fixtures/example_exercise.json`, `example_health_25_Day.json`, `example_health_90_Day.json`) — replaced with a placeholder (`00000001`); no test asserts on the literal value.
- `display_hr`-style debug script (`debug.py`, a personal manual-testing script with real training-plan text) and the old `deploy.sh` (hardcodes the old account's real ECR repo name) were dropped, same reasoning as the other services.

**Real fixes made during the `uv`/test-coverage pass:**
- `test_prompt.py` used to hit real S3 with no mocking at all — now uses `moto`.
- `whatsapp_adapter/push_notification.py` loaded Secrets Manager config at *import* time (`config = config_loader()` at module scope), which broke testability the same way `health-sync`'s equivalent did — moved inside `__init__`.
- **Real bug**: the long-message splitter built its split point as `rfind(...) or rfind(...) or rfind(...)`, relying on a failed `rfind` returning something falsy to fall through to the next attempt. `str.rfind` returns `-1` on no match, which is truthy in Python — so the chain always stopped at the first (failing) `rfind` and fell back to a hard character-count cut, splitting messages mid-word. Fixed to check `== -1` explicitly; caught by a test that actually inspects the split output instead of mocking `send_note`'s HTTP call away.
- `whatsapp_adapter/{event_handler.py, lambda_handler.py}` and `core/answer.py` had zero tests before this pass; all three now do.

**`core/transform/{exercise,health}.py` now have dedicated test suites** (27 tests). Writing them surfaced two more real bugs:
- `Exercise._calculate_load_trend`: `change_pct = last_week - prev_mean / prev_mean` — operator precedence means this always evaluates to `last_week - 1`, not `(last_week - prev_mean) / prev_mean`. Since `last_week` (a cardio-load sum) is essentially always > 1.1, this made every trend report `"increasing"` regardless of the actual data. Fixed by adding the parentheses the formula actually needs.
- `Helpers.helper_trend_analysis`: when fewer than 3 data points are available, only `trend` was set to `np.nan` in the `else` branch — `trend_per_week` was left unassigned but still referenced in the return dict, raising `UnboundLocalError` and crashing `health_summary()` outright for any column with sparse data. Fixed by assigning `trend_per_week = np.nan` alongside it.

## `get_exercise_metrics()` / `Exercise.exercise_summary()` output shape

A real example (`training_load`/`long_run_metrics` shown per 7/28/90d window; `load_management`/`intensity_distribution`/`aerobic_efficiency`/`endurance_signals` follow the same per-window pattern, omitted here for brevity):

```json
{
  "training_load": {
    "7d": {
      "total_cardio_load": 180.0,
      "total_distance_miles": 22.0,
      "total_duration_hr": 4.5,
      "runs": 2,
      "longest_run_miles": 14.0,
      "total_elevation_gain_ft": 2750,
      "elevation_gain_ft_per_mile": 125.0,
      "total_elevation_descent_ft": 2550,
      "elevation_descent_ft_per_mile": 115.9
    }
  },
  "long_run_metrics": {
    "7d": {
      "distance_m": 14.0,
      "duration_hr": 3.0,
      "avg_hr": 145,
      "hr_drift": 3.5,
      "gain_ft": 2100,
      "gain_ft_per_mile": 150.0,
      "descent_ft": 1950,
      "descent_ft_per_mile": 139.3,
      "zone2_pct": 48,
      "zone3_pct": 24
    }
  },
  "long_run_history": [
    {
      "date": "2026-01-01",
      "distance": 14.0,
      "duration_hr": 3.0,
      "gain_ft": 2100,
      "gain_ft_per_mile": 150.0,
      "descent_ft": 1950,
      "descent_ft_per_mile": 139.3,
      "avg_hr": 145,
      "hr_drift_pct": 3.5,
      "avg_pace": 12.9,
      "terrain": null
    }
  ],
  "validity_metrics": {"90d_sample_days": 3, "28d_sample_days": 3, "7d_sample_days": 2},
  "trend_analysis": {"weekly_distance_trend": 13.67, "long_run_trend": 1.33}
}
```

`total_elevation_gain_ft`/`total_elevation_descent_ft` (training load) and `gain_ft`/`descent_ft` (long run metrics/history) are **cumulative totals in feet**, even in the 28d/90d windows (unlike the `avg_weekly_*` fields alongside them — vert accumulation toward a fixed goal is a total, not a rate). Sourced from `exercise-etl`'s `elevation_ascent`/`elevation_descent` (already converted metres→feet at write time), so no unit conversion happens in this service. Omitted from the output entirely (not `null`) for any period where no underlying record has the field — e.g. records written before elevation capture existed.

`elevation_gain_ft_per_mile`/`elevation_descent_ft_per_mile`/`gain_ft_per_mile`/`descent_ft_per_mile` are **density** (total ÷ distance), not just totals — a race has a fixed elevation-per-distance profile (e.g. 7,000ft over 48mi ≈ 146 ft/mile), so density is what's actually comparable against it. Omitted (not `0`) when distance is 0 or unknown.

`long_run_history` is the **one field in this whole payload that's a real per-run array, not an aggregate** — the top 10 runs by distance within the trailing 90 days (not a fixed distance/duration threshold). `terrain` is always `null` today; no data source exists for it yet.

# Polar Web App — AI Running Coach

A single-page web app where an authenticated athlete chats with a Claude-backed
coach about their real Polar exercise data. The coach calls out to the
[`exercise-insights`](../../services/exercise-insights) service (as a local
Python dependency, not over the network) for training metrics, remembers the
athlete's goals across sessions, and avoids re-fetching/re-sending the same
training data on every message.

Originally built as a generic single-agent demo against mock sales data (see
git history) — now wired to this repo's real exercise data instead.

## Layout

```
src/
  main.py          # entry point — launches uvicorn
  app.py            # FastAPI: pages, auth, /ask + /plan/ask (SSE), rate limiting, onboarding/memory wiring
  agent.py           # Agent interface + ClaudeAgent (streaming + tool loop + prompt caching)
  tools.py            # get_my_training_data / save_athlete_profile / save_training_plan + the tool registry
  commands.py          # slash commands: /profile, /update-profile, /refresh-data, /help
  context_store.py      # S3-backed per-user profile/plan + conversation persistence
  plan.py                # shared pydantic validation for a training plan (manual edits + the LLM tool)
  config.py                # all settings (incl. both system prompts), driven by env / .env
  static/
    index.html       # the chat UI (served only to authenticated sessions)
    app.js            # chat streaming logic (no auth code)
    plan.html          # the training-plan page (chart, themes, weekly table, its own chat)
    plan.js             # plan page logic
    sse.js               # shared SSE-stream parsing, used by both app.js and plan.js
    login.html         # dedicated login page — a plain form, no JS
    vendor/
      chart.umd.min.js # pinned Chart.js build (no CDN, no bundler — see vendor/README.md)
```

Auth (Supabase sign-in + server-side session store) lives inline in
[src/app.py](src/app.py), not a separate `auth.py`.

## Setup

1. Install dependencies. This project depends on
   [`services/exercise-insights`](../../services/exercise-insights) as a local
   editable package (see `pyproject.toml`'s `[tool.uv.sources]`), so it must be
   run from within a checkout of this whole repo, not standalone:

   ```sh
   uv sync
   ```

2. Configure credentials:

   ```sh
   cp .env.example .env
   # edit .env — see the comments in .env.example for what each value is
   ```

   Get the Supabase values from your project dashboard → **Project Settings →
   API**: `SUPABASE_URL` and `SUPABASE_KEY` (the anon/publishable key). Both are
   used server-side only — neither is sent to the browser. Create a user under
   **Authentication → Users** to sign in with.

   `POLAR_USER_ID`/`CONTEXT_BUCKET`/AWS credentials are needed for the real
   exercise-data tool and profile/conversation persistence to work — see
   `.env.example`'s comments. Locally, `AWS_PROFILE=polar-app-prod` (per this
   repo's `~/.aws/config` convention) may already cover the AWS credential
   fields instead of setting them explicitly in `.env`.

3. Run:

   ```sh
   uv run python -m src.main
   ```

   Open http://127.0.0.1:8000, sign in, and ask something like *"How's my
   training going this week?"* On first use (no stored profile yet) the coach
   asks a few onboarding questions — sport, goal, timeline, constraints,
   training preferences, and how you'd like it to communicate — before
   giving substantive advice.

## Deploying (Raspberry Pi)

This app doesn't deploy to AWS. It's built as a Docker image (build context is
the **repo root**, not this directory — see `Dockerfile`'s header comment),
pushed to a private GitHub Container Registry image by
[`.github/workflows/deploy-web-app.yml`](../../.github/workflows/deploy-web-app.yml)
(manual dispatch only), and run on a Raspberry Pi. See
[docs/runbooks/raspberry-pi-web-app.md](../../docs/runbooks/raspberry-pi-web-app.md)
for the full one-time setup + update procedure.

## Authentication & rate limiting

Auth is **handled entirely server-side** — no auth code, and no token, ever
reaches the browser.

Flow:

1. A dedicated **`/login`** page is a plain HTML form that posts email/password
   to **`POST /auth/login`**.
2. The backend authenticates against Supabase with the **Python client**
   ([`sign_in_with_password`](https://supabase.com/docs/reference/python/auth-signinwithpassword)),
   stores the resulting tokens in a **server-side session store**, and sends the
   browser only an **opaque session id** in an HttpOnly cookie (never a JWT).
3. **`GET /`** and **`POST /ask`** are gated by looking that id up in the store
   (a dict lookup, no network call) via the dependencies in
   [src/app.py](src/app.py). An unauthenticated `GET /` redirects to `/login`;
   an unauthenticated `POST /ask` returns 401.
4. **`POST /auth/logout`** drops the session and clears the cookie.

Sign-up is not exposed — create users in the Supabase dashboard. The session
expires when its access token does; there is no refresh-token handling yet, so
the user signs in again afterwards. For production, set `COOKIE_SECURE=true`
(requires HTTPS).

> The session store is an in-process dict: sessions are lost on restart and are
> not shared across worker processes. Fine for this single-process app; swap it
> for Redis (or similar) to scale out. (This is separate from the athlete
> profile/conversation history, which persists in S3 — see below.)

Rate limiting uses [slowapi](https://github.com/laurentS/slowapi). `/ask` is
limited per authenticated user (falling back to client IP) via `RATE_LIMIT_ASK`
(default `20/minute`), and `/auth/login` via `RATE_LIMIT_LOGIN` (default
`10/minute`). Exceeding a limit returns HTTP 429.

## Athlete profile, memory, and slash commands

- **Profile** — sport, goal, goal date, desired outcome, constraints, training
  preferences, and communication style (tone, brevity, directness — separate
  from training preferences, which is about methodology, not delivery).
  Gathered conversationally the first time an athlete uses the app (no
  profile stored yet), then reused on every later session without re-asking.
  Persisted in S3 as `{user_id}/profile.json`
  ([src/context_store.py](src/context_store.py)). The coach adapts *how* it
  communicates to the stated style; the rigor of the analysis itself never
  changes.
- **Memory** — conversation history persists in S3 too
  (`{user_id}/conversation.json`), replayed into the model on every request.
  This is what lets the training-data tool result fetched on turn 1 stay
  usable on turn 5 without re-fetching or re-sending it — combined with
  Anthropic prompt caching (`cache_control` in [src/agent.py](src/agent.py))
  on both the system prompt and the training-data tool result, this is the
  main lever for keeping token costs down across a conversation.
- **Bounded history** — only the last `MAX_HISTORY_TURNS` turns (default 10)
  are kept; older ones are dropped (`context_store.append_messages`). Without
  this, both the replayed history and the prompt cache that mirrors it grow
  without limit over a long coaching relationship — confirmed live, a real
  conversation reached ~100k cached tokens before this was added.
- **Same-day data cache** — `get_my_training_data` only hits DynamoDB once per
  calendar day per athlete (Polar watch syncs land roughly daily); later calls
  the same day reuse the cached copy.
- **Slash commands** ([src/commands.py](src/commands.py)), Claude-Code-style:
  - `/profile` — show the stored profile (no LLM call).
  - `/update-profile` — revise it conversationally, any time.
  - `/refresh-data` — force a fresh fetch, bypassing the same-day cache.
  - `/reset-history` — clear conversation history; profile and cached
    training data are kept.
  - `/usage` — show token usage for today and this month.
  - `/help` — list commands.

## Training plan

A separate page (**`/plan`**, linked from the main chat header) where an
athlete builds a multi-week training plan and tracks it against real Polar
data — planned vs. actual distance/duration/elevation gain per week, and
named themes (e.g. "Base building", "Taper") spanning some subset of the
weeks, not required to be contiguous.

- **`GET /plan`** serves the page; **`GET /plan/data`** returns
  `{"plan": {...}|null, "actuals": [...]}` — the stored plan (if any) plus
  actuals computed live from real exercise data every request (never
  persisted — see `exercise_insights.core.get_weekly_actuals`, which buckets
  the same raw DynamoDB query `get_exercise_metrics` uses, by week instead of
  by rolling 7/28/90-day windows).
- **`POST /plan/edit`** is the manual-edit path — a full replace of the
  stored plan, validated by the same `plan.TrainingPlan` model the LLM tool
  uses (`plan.py`), so the two write paths can never produce differently-shaped
  plans.
- **`POST /plan/ask`** is a second chat, scoped to plan creation/editing —
  its own agent persona (see below), its own conversation history
  (`{user_id}/plan_conversation.json`, kept separate from the coach's own so
  neither history's growth silently doubles), and no slash-command routing.
  Calling `save_training_plan` here (or from the main coach chat, which can
  see it too) is what actually persists a plan; describing one in the chat
  alone does nothing.
- The main coach chat is aware of the current plan (injected into its
  `extra_system`, same mechanism as the stored profile) but is instructed not
  to try to edit it — that's the plan page's job.

## Configuring the agent

Everything tunable is in [src/config.py](src/config.py) and overridable via
`.env` — model, max tokens, max history turns, adaptive thinking, title,
host/port, `POLAR_USER_ID`, `CONTEXT_BUCKET`. No `temperature` setting —
Claude Sonnet 5 (and virtually every current-generation model) rejects
non-default `temperature`/`top_p`/`top_k` outright; tone is a prompting
concern, handled in `DEFAULT_SYSTEM_PROMPT`'s OUTPUT FORMAT section.

### Editing the live system prompts

Both agent personas are read from S3 at request time and fall back to a
`config.py` default (still fully env-overridable) if the object doesn't
exist yet — no `{user_id}/` prefix on either, they're global, not per-athlete:

- The **coach** (`/ask`): `context_store.get_system_prompt()`,
  `system_prompt.txt` / `DEFAULT_SYSTEM_PROMPT`.
- The **plan-building persona** (`/plan/ask`):
  `context_store.get_plan_system_prompt()`, `plan_system_prompt.txt` /
  `DEFAULT_PLAN_SYSTEM_PROMPT`.

To edit either without a redeploy:

```sh
# CONTEXT_BUCKET is the bucket name from your .env / terraform output
read -r CONTEXT_BUCKET
aws s3 cp new_prompt.txt "s3://$CONTEXT_BUCKET/system_prompt.txt" --profile polar-app-prod
aws s3 cp new_plan_prompt.txt "s3://$CONTEXT_BUCKET/plan_system_prompt.txt" --profile polar-app-prod
```

Anthropic's prompt cache is content-addressed, so an edited prompt naturally
invalidates the old cache entry on its own — no manual cache-busting needed.

## Adding or changing tools

Tools live in [src/tools.py](src/tools.py). Register a function with the `@tool`
decorator and it is automatically offered to the agent — see
`get_my_training_data`/`save_athlete_profile` for the current examples.

## Swapping the agent backend

[src/agent.py](src/agent.py) defines a small `Agent` interface. `ClaudeAgent`
implements it against the Anthropic API. To use a different backend, write
another `Agent` subclass and return it from `build_agent()`; the web layer is
unaffected.

## Tests

```sh
uv run coverage run -m unittest discover -s tests -t .
uv run coverage report
```

Covers tools, S3 persistence, slash commands, and (via `test_app.py`'s
`TestClient`-based tests and `test_agent_stream.py`'s fake-Anthropic-client
tests) `app.py`'s full HTTP/routing/auth surface and `agent.py`'s streaming
loop, mocking only the true external boundaries (Supabase, the Anthropic
streaming client, S3 via `moto`) — see `pyproject.toml`'s `fail_under`
comment for the current baseline.

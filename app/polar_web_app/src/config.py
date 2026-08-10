"""Application configuration.

Everything tunable about the agent and the web app lives here, driven by
environment variables (optionally via a local ``.env`` file). Change a value in
``.env`` and restart — no code edits required.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = """\
You are an endurance running coach and sports performance analyst specialising in ultramarathon preparation.

Analyse the athlete's real training metrics and give objective feedback on progress toward their goal. Behave like a data-driven coach: \
draw on the athlete's own stated training philosophy (in their profile, if given) rather than assuming one of your own.

CRITICAL RULES

1. Never invent or assume data.
2. Only analyse metrics present in the JSON the `get_my_training_data` tool returns.
3. If a metric is missing, state that clearly.
4. If a time window has insufficient data validity, ignore it completely.
5. All conclusions must reference the metrics used.
6. Do not provide generic running advice unless supported by the data.

VALIDITY RULES

7-day metrics: always valid if present.
28-day metrics: only analyse with at least 14 days of data in the aggregation.
90-day metrics: only analyse with at least 40 days of data in the aggregation.

If a window is invalid, state: "<window> metrics ignored due to insufficient data."

COACHING PRIORITIES

Evaluate across: Training Load Progression, Load Management Safety, Intensity Distribution, Aerobic Efficiency Development, Endurance \
Durability Signals, Long Run Development. Always base conclusions on measurable indicators.

OUTPUT FORMAT

Match the length of your answer to the question. A quick question gets a direct, short answer -- a few sentences, no forced structure. \
Reserve the full report below for when the athlete explicitly asks for a full review or progress check, or during onboarding:

Progress Toward Goal, Training Load Analysis, Intensity Distribution, Aerobic Efficiency, Endurance Durability, Long Run Readiness, \
Key Positive Signals (2-3 bullets), Potential Risks or Limiters, Coaching Recommendations.

Only include a section when you have something concrete and data-backed to say -- skip sections with nothing new rather than padding \
them out.

Analysis must always be analytical, objective, and evidence-based -- this never changes. How you communicate it can: if the athlete's \
profile states a `communication_style` (tone, brevity, directness), adapt your delivery to match it. With no stated preference, default \
to a clear, professional tone.

TRAINING DATA

Call the `get_my_training_data` tool to load the athlete's real training metrics before answering any question that needs them -- never \
guess or fabricate numbers. If the metrics are already visible earlier in this conversation, reuse them instead of calling the tool \
again; the tool itself only returns fresh data once per calendar day regardless; the athlete can force a real refresh with \
`/refresh-data`, at which point you should call the tool again even if you already have data in context.

ATHLETE PROFILE

Athlete-specific context (sport, goal, goal date, desired outcome, constraints, training philosophy, communication style) is provided \
separately, either as the athlete's existing stored profile or as an instruction to gather one because none exists yet. Follow whichever \
applies:

- If you are told the athlete has no profile yet: before giving substantive coaching advice, gather the missing fields through natural \
conversation -- one or two questions at a time, not an interrogation. Once you have enough (sport, goal, roughly when they want to \
achieve it, what success looks like, any constraints such as injuries/time/equipment, their training philosophy, and how they'd like \
you to communicate), call `save_athlete_profile` to store it, briefly confirm what you saved, and then proceed to help them.
- If you are given the athlete's existing profile: use it to frame your coaching (their stated goal, timeline, constraints, philosophy, \
and communication style) without re-asking for it. If the athlete mentions a change, update the stored profile by calling \
`save_athlete_profile` again with the revised fields.

The athlete can also explicitly revise their profile at any time with `/update-profile`, or check what's currently stored with \
`/profile` -- mention these if it's natural to do so, but don't recite them unprompted.
"""


DEFAULT_PLAN_SYSTEM_PROMPT = """\
You are a training-plan construction specialist, working with the athlete to build or revise a multi-week training plan. \
You are not the general coaching Q&A assistant -- keep this conversation scoped to building and adjusting the plan.

CRITICAL RULES

1. Never invent training numbers. Call the `get_my_training_data` tool before proposing weekly distance, duration, or \
elevation gain, and ground your proposal in the athlete's real recent fitness and typical elevation profile.
2. A plan has a start date (the Monday the first week begins), a list of weeks (each with planned distance in miles, \
duration in hours, and elevation gain in feet), and a list of themes (a short label plus which weeks it applies to -- \
themes do not have to be contiguous, and can overlap).
3. Once the athlete has confirmed enough detail (how many weeks, roughly what volume, any themed periods they want), call \
`save_training_plan` with the *whole* plan -- every week's numbers and every theme -- not just a prose description of \
what it should be. Saving is how the plan actually gets created or updated; describing it in the chat alone does nothing.
4. Keep theme labels short: 2-5 words, e.g. "Base building", "Taper", "Peak week". Pick a distinct color (a 6-digit hex \
string) for each theme.
5. If the athlete asks something outside plan construction (e.g. general coaching advice unrelated to the plan), answer \
briefly if it's directly relevant to planning, otherwise point them to the main coach chat.

CONVERSATION STYLE

Gather what you need through natural conversation -- one or two questions at a time, not a form. If the athlete already \
has a plan (given to you as context), you're revising it: only change what they've asked for, keep everything else as-is, \
and always call `save_training_plan` with the complete updated plan (unchanged weeks/themes included), since it replaces \
the whole stored plan rather than patching it.
"""


class Settings(BaseSettings):
    """Typed, env-driven settings for the agent and server.

    Override any field with an environment variable of the same name
    (case-insensitive), e.g. ``MODEL=claude-haiku-4-5`` or a line in ``.env``.
    """

    model_config = SettingsConfigDict(env_file=".env")

    # --- Credentials ---
    # Read from ``ANTHROPIC_API_KEY`` (env var or ``.env``). pydantic-settings
    # does not export ``.env`` into ``os.environ``, so we load the key here and
    # hand it to the SDK explicitly. Left as None when unset so the SDK can
    # still fall back to an env var exported directly in the shell.
    anthropic_api_key: str | None = None

    # --- Agent behaviour ---
    model: str = "claude-sonnet-5"
    # Fallback only -- the live prompt is read from S3 (context_store.get_system_prompt(),
    # `system_prompt.txt` in CONTEXT_BUCKET) so it's hot-editable without a redeploy. This
    # value is what's used until that object exists, and stays fully env-overridable.
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    # Fallback for the separate plan-construction agent persona (see agent.py's
    # base_system param) -- same S3-hot-editable, env-overridable shape as
    # system_prompt above, just a different live object
    # (context_store.get_plan_system_prompt(), `plan_system_prompt.txt`).
    plan_system_prompt: str = DEFAULT_PLAN_SYSTEM_PROMPT
    max_tokens: int = 4096
    # No `temperature` setting: Claude Sonnet 5 (and virtually every current-generation
    # model) rejects non-default temperature/top_p/top_k with a 400 -- confirmed live.
    # A more consistent, less rambling tone is a prompting concern now (see
    # DEFAULT_SYSTEM_PROMPT's OUTPUT FORMAT section), not a sampling-parameter one.
    # Adaptive thinking trades latency for deeper reasoning. Off by default for
    # a snappy demo; set ENABLE_THINKING=true to turn it on.
    enable_thinking: bool = False
    # How many turns of conversation history to replay per request. Older turns
    # are dropped (see context_store.append_messages) -- without a bound this
    # grows, and the prompt cache that mirrors it, without limit over a long
    # coaching relationship.
    max_history_turns: int = 10

    # --- Exercise data ---
    # The single athlete's Polar user id (DynamoDB `exercise_data` partition
    # key), matching the env var name the whatsapp_adapter/exercise-insights
    # service already uses.
    polar_user_id: str = ""
    # S3 bucket holding per-user profile/conversation/usage JSON plus the
    # global `system_prompt.txt` (see context_store.py). No default -- must
    # be set explicitly so a missing bucket fails loudly rather than silently
    # writing nowhere.
    context_bucket: str = ""

    # --- Web app ---
    app_title: str = "AI Running Coach"
    host: str = "127.0.0.1"
    port: int = 8000

    # --- Supabase auth ---
    # The backend authenticates users against Supabase with the Python client.
    # ``supabase_url`` and ``supabase_key`` (the project's anon/publishable key)
    # are used server-side only — neither is ever handed to the browser.
    supabase_url: str | None = None
    supabase_key: str | None = None

    # --- Session cookie ---
    # The backend mints an opaque session id, keeps the Supabase tokens in a
    # server-side store keyed by it, and sends only this id to the browser in an
    # HttpOnly cookie. The cookie value is never a JWT.
    auth_cookie_name: str = "session_id"
    # Set true in production (HTTPS) so the cookie is only sent over TLS. Left
    # false so it works over http://127.0.0.1 in local development; the app logs
    # a warning at startup if this is false while bound to a non-loopback host.
    cookie_secure: bool = False

    # --- Rate limiting (slowapi) ---
    # Limit strings in slowapi/limits syntax, e.g. "20/minute" or "100/hour".
    rate_limit_ask: str = "20/minute"
    rate_limit_login: str = "10/minute"

    # --- Logging ---
    # Root log level (DEBUG, INFO, WARNING, ERROR). Logs are written both to the
    # console and to a rotating file under ``log_dir``.
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_file: str = "app.log"


settings = Settings()

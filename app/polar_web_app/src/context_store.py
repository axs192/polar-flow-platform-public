"""Per-user persistence + the global system prompts, in S3.

One object per user per kind (``{user_id}/profile.json``,
``{user_id}/plan.json``, ``{user_id}/conversation.json``,
``{user_id}/plan_conversation.json``, ``{user_id}/usage.json``),
read/written as a whole JSON blob each time -- simple and sufficient at
single-athlete message volume. Plus two global, non-per-user objects
(``system_prompt.txt``, ``plan_system_prompt.txt``) holding the live coach
and plan-chat system prompts as plain text, so they're hot-editable without a
redeploy. See ``config.context_bucket`` for where the bucket comes from.
"""

from __future__ import annotations

import json
import logging
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any

import boto3

from .config import settings

logger = logging.getLogger(__name__)

# Set once per request (in app.py, before the agent runs) so tool functions
# that don't otherwise receive the caller's identity can look it up.
current_user_id: ContextVar[str] = ContextVar("current_user_id")

def _empty_history() -> dict[str, Any]:
    # A fresh dict (and fresh inner list) every call -- a shared module-level
    # template would let one user's appended messages leak into every other
    # caller's "empty" history via the same mutable list object.
    return {
        "messages": [],
        "turn_lengths": [],
        "training_data": None,
        "training_data_fetched_at": None,
        "refresh_pending": False,
    }


_s3_client = None


def _s3() -> Any:
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def _profile_key(user_id: str) -> str:
    return f"{user_id}/profile.json"


def _conversation_key(user_id: str, kind: str = "conversation") -> str:
    return f"{user_id}/{kind}.json"


def _plan_key(user_id: str) -> str:
    return f"{user_id}/plan.json"


def _usage_key(user_id: str) -> str:
    return f"{user_id}/usage.json"


# Counters tracked per calendar day in the usage blob -- matches the fields
# agent.py accumulates from the Anthropic SDK's response usage.
_USAGE_COUNTERS = (
    "requests",
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


def _empty_usage_totals() -> dict[str, int]:
    return dict.fromkeys(_USAGE_COUNTERS, 0)


def _get_json(key: str) -> dict[str, Any] | None:
    client = _s3()
    try:
        obj = client.get_object(Bucket=settings.context_bucket, Key=key)
        return json.loads(obj["Body"].read())
    except client.exceptions.NoSuchKey:
        return None


def _put_json(key: str, data: dict[str, Any]) -> None:
    _s3().put_object(
        Bucket=settings.context_bucket,
        Key=key,
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def _get_text(key: str) -> str | None:
    client = _s3()
    try:
        obj = client.get_object(Bucket=settings.context_bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    except client.exceptions.NoSuchKey:
        return None


_SYSTEM_PROMPT_KEY = "system_prompt.txt"


def get_system_prompt() -> str:
    """The live system prompt, hot-editable in S3 without a redeploy.

    Global, not per-user (no ``{user_id}/`` prefix) -- one coach persona for
    the app, same as the code-level default it replaces. Falls back to
    ``settings.system_prompt`` (the hardcoded default, itself still
    env-overridable) when the S3 object doesn't exist yet, so the app never
    hard-fails on a missing object or an unreachable bucket.
    """
    return _get_text(_SYSTEM_PROMPT_KEY) or settings.system_prompt


_PLAN_SYSTEM_PROMPT_KEY = "plan_system_prompt.txt"


def get_plan_system_prompt() -> str:
    """The live plan-chat system prompt -- exact mirror of ``get_system_prompt``'s
    S3-with-fallback pattern, for the separate plan-construction agent persona
    (see ``config.DEFAULT_PLAN_SYSTEM_PROMPT``). Global, not per-user."""
    return _get_text(_PLAN_SYSTEM_PROMPT_KEY) or settings.plan_system_prompt


def get_profile(user_id: str) -> dict[str, Any] | None:
    """Return the athlete's stored context, or None if they haven't set one up."""
    return _get_json(_profile_key(user_id))


def save_profile(user_id: str, **fields: Any) -> dict[str, Any]:
    """Upsert the athlete's profile (sport/goal/goal_date/desired_outcome/etc)."""
    profile = {**fields, "updated_at": datetime.now(UTC).isoformat()}
    _put_json(_profile_key(user_id), profile)
    logger.info("Saved athlete profile for user_id=%s", user_id)
    return profile


def get_plan(user_id: str) -> dict[str, Any] | None:
    """Return the athlete's stored training plan, or None if they don't have one yet."""
    return _get_json(_plan_key(user_id))


def save_plan(user_id: str, **fields: Any) -> dict[str, Any]:
    """Upsert the athlete's training plan (start_date/weeks/themes) -- full replace,
    same shape as ``save_profile``."""
    plan = {**fields, "updated_at": datetime.now(UTC).isoformat()}
    _put_json(_plan_key(user_id), plan)
    logger.info("Saved training plan for user_id=%s", user_id)
    return plan


def get_history(user_id: str, kind: str = "conversation") -> dict[str, Any]:
    """Return the stored conversation state, or an empty shell for a new user.

    ``kind`` selects which chat surface's transcript this is -- the coach chat
    (the default, "conversation") or the training-plan chat
    ("plan_conversation"), each its own S3 object and independently windowed.
    Kept separate rather than interleaved: it's a genuinely separate chat
    surface, the coach's awareness of the plan is via context injection (see
    app.py's ``/ask``) not shared transcript replay, and interleaving would
    silently double the growth rate ``max_history_turns`` was specifically
    added to bound.
    """
    return _get_json(_conversation_key(user_id, kind)) or _empty_history()


def append_messages(
    user_id: str, new_messages: list[dict[str, Any]], kind: str = "conversation"
) -> None:
    """Persist newly-generated turns onto the end of the stored conversation,
    then window to the last ``settings.max_history_turns`` turns.

    ``turn_lengths`` records how many messages each call to this function
    added, so trimming can drop whole turns -- never mid-turn, which would
    split a tool_use/tool_result pair and break the next request. Each
    ``new_messages`` list is exactly one agent turn's worth of output
    (agent.py's stream()): always starts with a plain user message and ends
    with a plain, non-tool_use assistant message, by construction of its
    ``while True`` loop.

    Without a bound here, the replayed history -- and the prompt cache that
    mirrors it -- grows without limit over a long coaching relationship
    (confirmed live: a real conversation reached ~100k cached tokens).
    Existing stored conversations have no ``turn_lengths`` yet, so the first
    call after this ships trims down to just the newest turn -- a one-time
    reset of the oversized backlog, not a gradual rolloff.
    """
    data = get_history(user_id, kind)
    data["messages"].extend(new_messages)
    data.setdefault("turn_lengths", []).append(len(new_messages))

    keep_turns = data["turn_lengths"][-settings.max_history_turns :]
    keep_message_count = sum(keep_turns)
    data["messages"] = data["messages"][-keep_message_count:] if keep_message_count else []
    data["turn_lengths"] = keep_turns

    _put_json(_conversation_key(user_id, kind), data)


def clear_history(user_id: str, kind: str = "conversation") -> None:
    """Wipe the stored conversation transcript (the ``/reset-history`` command).

    Keeps the cached training-data blob/timestamp intact -- clearing the chat
    transcript is no reason to also force a redundant same-day data re-fetch.
    """
    data = get_history(user_id, kind)
    data["messages"] = []
    data["turn_lengths"] = []
    _put_json(_conversation_key(user_id, kind), data)


def get_cached_training_data(user_id: str) -> dict[str, Any] | None:
    """Training data fetched earlier today, if any -- else None (needs a fetch)."""
    data = get_history(user_id)
    fetched_at = data.get("training_data_fetched_at")
    if not fetched_at:
        return None
    fetched_date = datetime.fromisoformat(fetched_at).date()
    if fetched_date != date.today():
        return None
    return data.get("training_data")


def save_training_data(user_id: str, metrics: dict[str, Any]) -> None:
    """Cache a freshly-fetched metrics summary, timestamped for same-day reuse."""
    data = get_history(user_id)
    data["training_data"] = metrics
    data["training_data_fetched_at"] = datetime.now(UTC).isoformat()
    _put_json(_conversation_key(user_id), data)


def mark_refresh_pending(user_id: str) -> None:
    """Flag that /refresh-data just ran, for the agent to pick up on its next turn.

    /refresh-data returns a direct_reply (no LLM call), so that exchange is
    never added to the persisted conversation history (app.py's event_stream
    only appends messages from a "done" event carrying new_messages, which a
    direct-reply command_stream never yields). Without this flag, the model
    has no way to know a refresh happened -- it just reuses whatever
    get_my_training_data tool_result already sits earlier in its own context,
    per the system prompt's own "reuse if visible" instruction. Confirmed
    live: this was the actual root cause of the athlete seeing stale numbers
    right after running /refresh-data.
    """
    data = get_history(user_id)
    data["refresh_pending"] = True
    _put_json(_conversation_key(user_id), data)


def consume_refresh_pending(user_id: str) -> bool:
    """True if a refresh just happened and hasn't been surfaced to the agent
    yet -- clears the flag so it fires on exactly the next turn, not every
    turn afterward."""
    data = get_history(user_id)
    pending = data.get("refresh_pending", False)
    if pending:
        data["refresh_pending"] = False
        _put_json(_conversation_key(user_id), data)
    return pending


def record_usage(user_id: str, usage: dict[str, int]) -> None:
    """Add one agent turn's token usage onto today's running total.

    Stored as ``{"days": {"<ISO date>": {counter: total, ...}, ...}}`` --
    bucketed per day (not per request) so the blob stays small indefinitely,
    unlike the conversation transcript (see the Open Items note on
    unbounded history growth).
    """
    data = _get_json(_usage_key(user_id)) or {"days": {}}
    today = date.today().isoformat()
    bucket = data["days"].setdefault(today, _empty_usage_totals())
    bucket["requests"] += 1
    for field in _USAGE_COUNTERS[1:]:
        bucket[field] += usage.get(field, 0) or 0
    _put_json(_usage_key(user_id), data)


def get_usage_summary(user_id: str) -> dict[str, dict[str, int]]:
    """Token usage totals for today and for the current calendar month."""
    data = _get_json(_usage_key(user_id)) or {"days": {}}
    today = date.today().isoformat()
    month_prefix = today[:7]  # "YYYY-MM"

    today_totals = _empty_usage_totals()
    month_totals = _empty_usage_totals()
    for day, counters in data["days"].items():
        if day == today:
            for field in _USAGE_COUNTERS:
                today_totals[field] += counters.get(field, 0)
        if day.startswith(month_prefix):
            for field in _USAGE_COUNTERS:
                month_totals[field] += counters.get(field, 0)

    return {"today": today_totals, "month_to_date": month_totals}

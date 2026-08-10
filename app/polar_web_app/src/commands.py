"""Slash commands: intercepted in ``POST /ask`` before the message reaches the
agent, Claude-Code-style.

``/profile``, ``/help``, and ``/refresh-data`` are handled directly (no LLM
call needed). ``/update-profile`` still needs a conversational turn to gather
what changed, so it falls through to the agent with an extra system
instruction telling it what the command means.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import context_store
from .tools import get_my_training_data

COMMANDS: dict[str, str] = {
    "/profile": "Show your currently stored coaching profile.",
    "/update-profile": "Revise your goal, timeline, constraints, or preferences.",
    "/refresh-data": "Force a fresh pull of your training data, bypassing today's same-day cache.",
    "/reset-history": "Clear your conversation history. Your profile and cached training data are kept.",
    "/usage": "Show your token usage for today and this month.",
    "/help": "List available commands.",
}


@dataclass
class CommandOutcome:
    """Either a direct reply (no LLM call), or extra system context for the
    agent to handle the turn with."""

    direct_reply: str | None = None
    extra_system: str | None = None


def is_command(question: str) -> bool:
    return question.strip().startswith("/")


def format_profile(profile: dict | None) -> str:
    if not profile:
        return (
            "You don't have a coaching profile saved yet -- just start chatting "
            "and I'll ask what I need to know."
        )
    fields = [
        ("Sport", profile.get("sport")),
        ("Goal", profile.get("goal")),
        ("Goal date", profile.get("goal_date")),
        ("Desired outcome", profile.get("desired_outcome")),
        ("Constraints", profile.get("constraints")),
        ("Training preferences", profile.get("training_preferences")),
        ("Communication style", profile.get("communication_style")),
    ]
    return "\n".join(f"**{label}:** {value or '-'}" for label, value in fields)


def format_usage(summary: dict[str, dict[str, int]]) -> str:
    today = summary["today"]
    month = summary["month_to_date"]
    if today["requests"] == 0 and month["requests"] == 0:
        return "No usage recorded yet -- ask something and check back."

    def line(label: str, totals: dict[str, int]) -> str:
        return (
            f"**{label}:** {totals['requests']} request(s) -- "
            f"{totals['input_tokens']:,} input / {totals['output_tokens']:,} output tokens "
            f"({totals['cache_read_input_tokens']:,} cache-read / "
            f"{totals['cache_creation_input_tokens']:,} cache-write)"
        )

    return line("Today", today) + "\n" + line("This month", month)


def handle_command(question: str, user_id: str) -> CommandOutcome:
    """Route a slash command. Assumes ``is_command(question)`` is already True."""
    cmd = question.strip().split()[0].lower()

    if cmd == "/profile":
        return CommandOutcome(direct_reply=format_profile(context_store.get_profile(user_id)))

    if cmd == "/help":
        listing = "\n".join(f"`{name}` -- {desc}" for name, desc in COMMANDS.items())
        return CommandOutcome(direct_reply=listing)

    if cmd == "/reset-history":
        context_store.clear_history(user_id)
        return CommandOutcome(
            direct_reply="Conversation history cleared -- your profile and cached training data are untouched."
        )

    if cmd == "/usage":
        return CommandOutcome(direct_reply=format_usage(context_store.get_usage_summary(user_id)))

    if cmd == "/refresh-data":
        token = context_store.current_user_id.set(user_id)
        try:
            get_my_training_data(force_refresh=True)
        finally:
            context_store.current_user_id.reset(token)
        # This command replies directly (no LLM call), so this exchange is
        # never added to the conversation history the agent replays -- the
        # agent otherwise has no way to know a refresh happened, and would
        # just reuse stale values already in its context. The flag makes the
        # *next* turn tell it to call get_my_training_data again regardless.
        context_store.mark_refresh_pending(user_id)
        return CommandOutcome(
            direct_reply="Training data refreshed. Ask me anything and I'll use the latest numbers."
        )

    if cmd in ("/update-profile", "/profile-edit"):
        existing = context_store.get_profile(user_id)
        instruction = (
            "The athlete just ran the /update-profile command, which means they want to "
            "revise their coaching profile. Ask what's changed -- goal, timeline, desired "
            "outcome, constraints, training preferences, or communication style -- through "
            "natural conversation, one or two questions at a time. Once you have the "
            "update, call save_athlete_profile with the full set of fields (carry over "
            f"anything that didn't change from their current profile below). Current "
            f"profile: {json.dumps(existing) if existing else 'none saved yet'}."
        )
        return CommandOutcome(extra_system=instruction)

    return CommandOutcome(
        direct_reply=f"Unknown command '{cmd}'. Try `/help` for the list of available commands."
    )

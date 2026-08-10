"""Tools the agent can call.

A tool is a plain Python function plus a JSON schema describing its inputs.
Register one with the ``@tool`` decorator and it is automatically exposed to the
agent — no other wiring needed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from . import context_store
from .config import settings
from .plan import TrainingPlan

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Tool:
    """A callable tool together with the schema sent to the model."""

    name: str
    description: str
    input_schema: dict[str, Any]
    fn: Callable[..., Any]

    @property
    def schema(self) -> dict[str, Any]:
        """The tool definition in the shape the Anthropic API expects."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


# The registry. Populated by the @tool decorator below.
_REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, input_schema: dict[str, Any]):
    """Decorator that registers a function as an agent tool."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _REGISTRY[name] = Tool(name, description, input_schema, fn)
        return fn

    return decorator


def tool_schemas() -> list[dict[str, Any]]:
    """All registered tool definitions, for the ``tools=`` API parameter."""
    return [t.schema for t in _REGISTRY.values()]


def run_tool(name: str, tool_input: dict[str, Any]) -> Any:
    """Execute a registered tool by name and return its (JSON-serialisable) result."""
    if name not in _REGISTRY:
        logger.warning("Unknown tool requested: %s", name)
        return {"error": f"Unknown tool: {name}"}
    logger.info("Running tool %s with input=%s", name, tool_input)
    result = _REGISTRY[name].fn(**tool_input)
    logger.debug("Tool %s returned %s", name, result)
    return result


# ---------------------------------------------------------------------------
# Real tools: exercise data (via the exercise-insights service) and the
# athlete's coaching profile (via context_store, backed by S3).
# ---------------------------------------------------------------------------


@tool(
    name="get_my_training_data",
    description=(
        "Load the athlete's real running training metrics (7/28/90-day training load, "
        "intensity distribution, aerobic efficiency, endurance durability, long-run "
        "readiness) as structured JSON. Call this before answering any question that "
        "needs real numbers -- never guess or invent data. If the metrics are already "
        "visible earlier in this conversation, reuse them instead of calling this again; "
        "the tool itself only returns freshly-fetched data once per calendar day "
        "regardless of how often it's called."
    ),
    input_schema={"type": "object", "properties": {}},
)
def get_my_training_data(force_refresh: bool = False) -> dict[str, Any]:
    """Fetch (or reuse a same-day cached copy of) the athlete's exercise metrics.

    ``force_refresh`` is not exposed to the model (the tool's input schema
    takes no arguments) -- it's a hook for the ``/refresh-data`` slash command
    to bypass the same-day cache deliberately.
    """
    user_id = context_store.current_user_id.get()

    if not force_refresh:
        cached = context_store.get_cached_training_data(user_id)
        if cached is not None:
            logger.info("Reusing same-day cached training data for user_id=%s", user_id)
            return cached

    # Imported lazily: exercise_insights pulls in pandas/numpy/boto3, which
    # noticeably slows app startup (cold-import cost) if paid on every server
    # boot instead of only when this tool actually runs.
    from exercise_insights.core import get_exercise_metrics

    metrics = get_exercise_metrics(settings.polar_user_id)
    context_store.save_training_data(user_id, metrics)
    return metrics


@tool(
    name="save_athlete_profile",
    description=(
        "Save or update the athlete's coaching context: sport, goal, goal date, desired "
        "outcome, constraints, preferred training approach, and how they'd like the coach "
        "to communicate. Call this once you've gathered enough detail during onboarding, "
        "or any time the athlete tells you something about their goal, situation, or "
        "communication preferences has changed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "sport": {
                "type": "string",
                "description": "The athlete's primary sport, e.g. 'ultramarathon running'.",
            },
            "goal": {
                "type": "string",
                "description": "The athlete's stated goal, e.g. '75km ultramarathon'.",
            },
            "goal_date": {
                "type": "string",
                "description": (
                    "When they want to achieve it, as free text (a date, or a rough "
                    "timeframe like 'next spring')."
                ),
            },
            "desired_outcome": {
                "type": "string",
                "description": "What success looks like to them, e.g. 'finish under 10 hours'.",
            },
            "constraints": {
                "type": "string",
                "description": "Injuries, time availability, equipment, or other constraints.",
            },
            "training_preferences": {
                "type": "string",
                "description": "Any training philosophy or approach they prefer.",
            },
            "communication_style": {
                "type": "string",
                "description": (
                    "How they want the coach to communicate: tone, level of detail, "
                    "directness (e.g. 'brief and blunt', 'detailed with the reasoning', "
                    "'encouraging and positive'). Separate from training_preferences, "
                    "which is about training methodology, not communication style."
                ),
            },
        },
        "required": ["sport", "goal"],
    },
)
def save_athlete_profile(
    sport: str,
    goal: str,
    goal_date: str = "",
    desired_outcome: str = "",
    constraints: str = "",
    training_preferences: str = "",
    communication_style: str = "",
) -> dict[str, Any]:
    """Persist the athlete's coaching profile (an upsert -- used for onboarding and edits)."""
    user_id = context_store.current_user_id.get()
    return context_store.save_profile(
        user_id,
        sport=sport,
        goal=goal,
        goal_date=goal_date,
        desired_outcome=desired_outcome,
        constraints=constraints,
        training_preferences=training_preferences,
        communication_style=communication_style,
    )


@tool(
    name="save_training_plan",
    description=(
        "Save or replace the athlete's training plan: a start date (the Monday week 1 "
        "begins), a list of weekly planned distance/duration/elevation gain, and a list of "
        "named themes (each spanning some subset of the weeks -- not required to be "
        "contiguous, and themes may overlap). Call this with the *whole* plan once the "
        "athlete has confirmed it -- this replaces the entire stored plan, it does not "
        "merge or patch a previous one."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "start_date": {
                "type": "string",
                "description": "The Monday week 1 begins, as an ISO date 'YYYY-MM-DD'.",
            },
            "weeks": {
                "type": "array",
                "description": "One entry per week, in order (week 0 first).",
                "items": {
                    "type": "object",
                    "properties": {
                        "planned_distance_miles": {"type": "number"},
                        "planned_duration_hr": {"type": "number"},
                        "planned_elevation_gain_ft": {"type": "number"},
                    },
                    "required": [
                        "planned_distance_miles",
                        "planned_duration_hr",
                        "planned_elevation_gain_ft",
                    ],
                },
            },
            "themes": {
                "type": "array",
                "description": (
                    "Named periods. Each theme's `weeks` is a list of 0-indexed positions "
                    "into the `weeks` array -- not required to be contiguous."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "label": {"type": "string", "description": "Short, e.g. 'Base building'."},
                        "weeks": {"type": "array", "items": {"type": "integer"}},
                        "color": {
                            "type": "string",
                            "description": "A 6-digit hex color, e.g. '#4a90d9'.",
                        },
                    },
                    "required": ["label", "weeks", "color"],
                },
            },
        },
        "required": ["start_date", "weeks"],
    },
)
def save_training_plan(
    start_date: str,
    weeks: list[dict[str, Any]],
    themes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Validate then persist the athlete's training plan (full-replace, an upsert).

    Returns ``{"error": ...}`` rather than raising on invalid input -- an
    uncaught exception would abort the whole SSE turn via agent.py's outer
    ``except Exception``, giving the model no chance to see what was wrong and
    retry, same convention ``run_tool`` already uses for "Unknown tool".
    """
    try:
        validated = TrainingPlan(start_date=start_date, weeks=weeks, themes=themes or [])
    except ValidationError as exc:
        return {"error": str(exc)}

    user_id = context_store.current_user_id.get()
    return context_store.save_plan(
        user_id,
        start_date=validated.start_date,
        weeks=[w.model_dump() for w in validated.weeks],
        themes=[t.model_dump() for t in validated.themes],
    )

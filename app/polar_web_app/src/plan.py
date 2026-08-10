"""Shared validation for a training plan.

Used by both the manual-edit HTTP route (``POST /plan/edit`` in ``app.py``)
and the LLM's ``save_training_plan`` tool (``tools.py``), so the two write
paths can never produce differently-shaped plans. Lives outside
``context_store.py`` (which stays deliberately dumb S3 I/O, like
``save_profile``'s bare ``**fields``) and outside ``tools.py``, so both
``app.py`` and ``tools.py`` can import it without a cycle.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field, field_validator, model_validator

_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


class PlanWeek(BaseModel):
    """One week's planned volume. Actuals are never stored -- always computed
    live from real exercise data (see ``exercise_insights.core.get_weekly_actuals``)."""

    planned_distance_miles: float = Field(ge=0)
    planned_duration_hr: float = Field(ge=0)
    planned_elevation_gain_ft: float = Field(ge=0)


class Theme(BaseModel):
    """A named period spanning some (not necessarily contiguous) subset of the
    plan's weeks -- e.g. "Base building" over weeks 0-3, or "Down week" as a
    single week 3 that overlaps it. Both gaps and overlap between themes are
    allowed, matching Polar's own Season Planner UI."""

    label: str = Field(min_length=1, max_length=60)
    # 0-indexed positions into TrainingPlan.weeks. Deliberately not a
    # start_week/end_week range -- a theme's weeks aren't always contiguous
    # ("week 1, gap week 2, week 3" is a real case a range can't express).
    # Range-validated against the plan's actual week count below, not here,
    # since a single Theme has no visibility into its parent plan's length.
    weeks: list[int] = Field(default_factory=list)
    color: str

    @field_validator("color")
    @classmethod
    def _validate_color(cls, v: str) -> str:
        if not _HEX_COLOR_RE.match(v):
            raise ValueError(f"color must be a 6-digit hex string like '#4a90d9', got {v!r}")
        return v


class TrainingPlan(BaseModel):
    """The athlete-supplied shape of a plan -- no ``updated_at``, which
    ``context_store.save_plan`` stamps server-side, same as ``save_profile``."""

    start_date: str = Field(min_length=1)
    # max_length is a generous sanity cap (10 years / a plan's worth of
    # themes), not a real product constraint -- defends against a malformed
    # client bug or an LLM tool call looping unboundedly, not a normal use case.
    weeks: list[PlanWeek] = Field(min_length=1, max_length=520)
    themes: list[Theme] = Field(default_factory=list, max_length=520)

    @field_validator("start_date")
    @classmethod
    def _validate_start_date(cls, v: str) -> str:
        # Plain ISO "YYYY-MM-DD" (a date input's native value, and this app's
        # only use of it -- 7*index days are added to it, never combined with
        # a time component), not the full datetime.fromisoformat surface.
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
            raise ValueError(f"start_date must be an ISO date 'YYYY-MM-DD', got {v!r}")
        return v

    @model_validator(mode="after")
    def _validate_theme_weeks(self) -> TrainingPlan:
        n = len(self.weeks)
        for theme in self.themes:
            for w in theme.weeks:
                if not (0 <= w < n):
                    raise ValueError(
                        f"theme {theme.label!r} references week index {w}, out of range "
                        f"for a {n}-week plan"
                    )
        return self

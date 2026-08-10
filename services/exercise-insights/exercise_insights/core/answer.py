"""Transport-agnostic Q&A logic: given a user's question, answer it using
their recent exercise history and an LLM.

No AWS-transport awareness here (no SQS parsing, no WhatsApp sending) - see
whatsapp_adapter/ for that. This is the seam a future webserver integration
calls into directly.
"""

import json
import logging
from datetime import datetime, timedelta

from openai import OpenAI

from exercise_insights.core.extract import dynamo_extract
from exercise_insights.core.prompts_loader import get_prompt
from exercise_insights.core.transform import Exercise
from exercise_insights.shared.config_loader import config_loader


def get_exercise_metrics(user_id: str, days: int = 90) -> dict:
    """Fetch and summarize a user's exercise history over the trailing window.

    Parameters
    ----------
    user_id : str
        The Polar user id whose data to draw on.
    days : int
        Size of the trailing window to query, in days.
    """
    now = datetime.now()
    start = now - timedelta(days=days)
    # Must match exercise-etl's actual write format exactly (load_creator.py:
    # date = response.get("start_time"), a raw Polar Accesslink ISO timestamp
    # like "2026-02-22T07:50:17") -- DynamoDB's BETWEEN on a String range key
    # is a lexicographic comparison, and "-" (0x2D) sorts before "/" (0x2F),
    # so a "%Y/%m/%d"-formatted bound can never match a "-"-formatted stored
    # value, for any date, ever. Confirmed live with a real moto-backed
    # query: the old slash format matched 0 of a real stored item; this
    # format matches it correctly. This is the actual root cause of a real
    # "AttributeError: 'Exercise' object has no attribute 'running_df'" (see
    # that fix in transform/exercise.py) -- the query wasn't returning
    # "genuinely no data in range", it was silently never matching real data
    # at all, on either this web app or the original WhatsApp Q&A path.
    end_date = now.strftime("%Y-%m-%dT%H:%M:%S")
    start_date = start.strftime("%Y-%m-%dT%H:%M:%S")

    records = dynamo_extract(table="exercise_data").get_records_bt_dates(
        uid=user_id, start_date=start_date, end_date=end_date
    )
    return Exercise(records).exercise_summary()


def get_weekly_actuals(user_id: str, start_date: str, weeks: int) -> list[dict]:
    """Bucket a user's real running records into per-week actuals for a
    training plan, aligned to the plan's own start date and length.

    Parameters
    ----------
    user_id : str
        The Polar user id whose data to draw on.
    start_date : str
        The plan's start date, ISO 'YYYY-MM-DD' (week 0 begins here, same
        positional-derivation convention the plan's own week dates use).
    weeks : int
        Number of weeks to bucket -- the plan's length.

    Returns a list of ``weeks`` dicts, one per week in order, each with
    ``actual_distance_miles``/``actual_duration_hr``/``actual_elevation_gain_ft``.
    A week that hasn't started yet gets ``None`` for all three (distinct from
    a week that happened with zero logged runs, which gets real 0.0s) so the
    frontend can render "not run yet" instead of a misleading zero.
    """
    date_format = "%Y-%m-%dT%H:%M:%S"  # see get_exercise_metrics's comment on why this exact format
    plan_start = datetime.strptime(start_date, "%Y-%m-%d")
    plan_end = plan_start + timedelta(days=7 * weeks)
    now = datetime.now()

    records = dynamo_extract(table="exercise_data").get_records_bt_dates(
        uid=user_id,
        start_date=plan_start.strftime(date_format),
        end_date=plan_end.strftime(date_format),
    )

    buckets: list[dict] = []
    for i in range(weeks):
        started = plan_start + timedelta(days=7 * i) <= now
        buckets.append(
            {
                "actual_distance_miles": 0.0 if started else None,
                "actual_duration_hr": 0.0 if started else None,
                "actual_elevation_gain_ft": 0.0 if started else None,
            }
        )

    for record in records:
        if record.get("sport") != "RUNNING":
            continue
        try:
            record_date = datetime.strptime(record["date"], date_format)
        except (KeyError, ValueError):
            continue
        week_index = (record_date - plan_start).days // 7
        if not (0 <= week_index < weeks):
            continue
        bucket = buckets[week_index]
        bucket["actual_distance_miles"] = (bucket["actual_distance_miles"] or 0) + (
            record.get("distance") or 0
        )
        bucket["actual_duration_hr"] = (bucket["actual_duration_hr"] or 0) + (
            record.get("durationSec") or 0
        ) / 3600
        bucket["actual_elevation_gain_ft"] = (bucket["actual_elevation_gain_ft"] or 0) + (
            record.get("elevation_ascent") or 0
        )

    return buckets


def answer_question(user_id: str, question: str) -> str:
    """Answer a question about the given user's exercise history.

    Parameters
    ----------
    user_id : str
        The Polar user id whose data to draw on.
    question : str
        The user's question, as free text.
    """
    config = config_loader()
    client = OpenAI(api_key=config["OPEN_AI_AUTH"])

    metrics = get_exercise_metrics(user_id)

    system_prompt = get_prompt(exercise=True)

    try:
        response = client.responses.create(
            model="gpt-5-mini",
            input=[
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": question},
                {
                    "role": "user",
                    "content": f"User's DATA to support request {json.dumps(metrics, indent=2)}",
                },
            ],
        )
        return response.output_text
    except Exception as e:
        logging.error("Error raising prompt with OpenAI: %s", e)
        raise

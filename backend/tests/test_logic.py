"""Unit tests for logic.py. Run from the backend/ folder with: pytest"""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from logic import (
    ValidationError,
    build_insights,
    build_reminder,
    format_weekly_email,
    local_date,
    summarize_day,
    validate_days,
    validate_goals,
    validate_meal,
    validate_sleep,
    validate_workout,
    workout_volume,
)

GOALS = {"calories": 2500, "protein_g": 150, "sleep_hours": 8}


# ---------- Validation ----------

def test_valid_meal_is_accepted():
    meal = validate_meal(
        {"date": "2026-10-11", "name": "  Chicken and rice ", "calories": 650, "protein_g": Decimal("45.5")}
    )
    assert meal["name"] == "Chicken and rice"  # whitespace trimmed
    assert meal["protein_g"] == Decimal("45.5")


def test_meal_without_name_is_rejected():
    with pytest.raises(ValidationError):
        validate_meal({"date": "2026-10-11", "calories": 650, "protein_g": 45})


def test_negative_calories_are_rejected():
    with pytest.raises(ValidationError):
        validate_meal({"date": "2026-10-11", "name": "Oats", "calories": -10, "protein_g": 5})


def test_true_is_not_a_number():
    with pytest.raises(ValidationError):
        validate_sleep({"date": "2026-10-11", "hours": True})


def test_impossible_date_is_rejected():
    with pytest.raises(ValidationError):
        validate_sleep({"date": "2026-02-30", "hours": 8})


def test_workout_requires_exercise_name():
    with pytest.raises(ValidationError):
        validate_workout({"date": "2026-10-11", "sets": 3, "reps": 8, "weight": 135})


def test_goals_default_to_reminders_on():
    goals = validate_goals({"calories": 2500, "protein_g": 150, "sleep_hours": 8})
    assert goals["reminders"] is True
    assert goals["utc_offset_minutes"] == 0


def test_goals_reject_bad_offset():
    with pytest.raises(ValidationError):
        validate_goals({**GOALS, "utc_offset_minutes": 5000})


def test_days_parameter():
    assert validate_days(None) == 7
    assert validate_days("28") == 28
    with pytest.raises(ValidationError):
        validate_days("0")


# ---------- Daily math ----------

def test_summary_without_goals():
    summary = summarize_day(meals=[], sleep=None, goals=None)
    assert summary["totals"] == {"calories": 0, "protein_g": 0, "sleep_hours": 0}
    assert summary["remaining"] is None


def test_summary_with_goals():
    meals = [
        {"calories": 600, "protein_g": Decimal("40")},
        {"calories": 800, "protein_g": Decimal("70.5")},
    ]
    summary = summarize_day(meals, {"hours": Decimal("8.5")}, GOALS)

    assert summary["totals"]["protein_g"] == Decimal("110.5")
    assert summary["remaining"]["protein_g"] == Decimal("39.5")
    assert summary["remaining"]["sleep_hours"] == Decimal("-0.5")  # slept past the goal
    assert summary["protein_goal_met"] is False
    assert summary["sleep_goal_met"] is True


def test_workout_volume():
    workouts = [{"sets": 3, "reps": 8, "weight": 135}, {"sets": 3, "reps": 10, "weight": 0}]
    assert workout_volume(workouts) == 3240  # bodyweight exercises add 0


# ---------- Insights ----------

def test_insights_compare_volume_after_good_and_short_sleep():
    data = {
        "2026-10-05": {"sleep": {"hours": 8}, "workouts": [{"sets": 1, "reps": 10, "weight": 100}],
                       "meals": [{"protein_g": 160}]},
        "2026-10-06": {"sleep": {"hours": 6}, "workouts": [{"sets": 1, "reps": 5, "weight": 100}],
                       "meals": [{"protein_g": 120}]},
    }
    insights = build_insights(data, GOALS, "2026-10-05", "2026-10-11")

    assert len(insights["daily"]) == 7  # empty days are still included
    assert insights["avg_volume_after_good_sleep"] == 1000
    assert insights["avg_volume_after_short_sleep"] == 500
    assert insights["protein_goal_days"] == 1
    assert insights["avg_protein_g"] == 140
    assert "Average volume after a full night" in format_weekly_email(insights)


def test_insights_with_no_data():
    insights = build_insights({}, None, "2026-10-05", "2026-10-11")
    assert insights["avg_sleep_hours"] is None
    assert "No meals logged" in format_weekly_email(insights)


# ---------- Reminders and time zones ----------

def test_local_date_uses_offset():
    # 00:30 UTC on the 12th is still 8:30pm on the 11th in New York (UTC-4).
    now = datetime(2026, 10, 12, 0, 30, tzinfo=timezone.utc)
    assert local_date(now, -240) == "2026-10-11"


def test_reminder_when_short_on_protein():
    summary = summarize_day([{"calories": 500, "protein_g": 40}], None, GOALS)
    message = build_reminder(summary, sleep_logged=False)
    assert "110g short" in message
    assert "sleep" in message


def test_no_reminder_when_everything_done():
    summary = summarize_day([{"calories": 2000, "protein_g": 160}], {"hours": 8}, GOALS)
    assert build_reminder(summary, sleep_logged=True) is None

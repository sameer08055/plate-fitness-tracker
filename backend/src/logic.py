"""
Pure business logic: validation, daily math, insights, and email text.

Nothing in this file talks to AWS or the internet, so all of it can be
unit tested on your laptop without credentials.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal


class ValidationError(Exception):
    """Raised when a request is missing fields or has bad values (-> HTTP 400)."""


# ---------- Small validation helpers ----------

def parse_date(value):
    """Check that a value is a real calendar date like '2026-10-11'."""
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        raise ValidationError(f"'{value}' is not a valid date. Use YYYY-MM-DD.")


def require_number(body, field, max_value):
    """Read a required number from the request body and check its range.

    JSON is parsed with Decimal for decimals (DynamoDB doesn't accept
    Python floats), so a valid number here is either an int or a Decimal.
    """
    value = body.get(field)
    # bool is a subclass of int in Python, so rule out true/false explicitly.
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        raise ValidationError(f"'{field}' is required and must be a number.")
    if value < 0 or value > max_value:
        raise ValidationError(f"'{field}' must be between 0 and {max_value}.")
    return value


def require_text(body, field, max_length, example):
    value = body.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"'{field}' is required, e.g. \"{example}\".")
    if len(value) > max_length:
        raise ValidationError(f"'{field}' must be {max_length} characters or fewer.")
    return value.strip()


# ---------- Request validation ----------

def validate_meal(body):
    return {
        "date": parse_date(body.get("date")),
        "name": require_text(body, "name", 100, "Chicken and rice"),
        "calories": require_number(body, "calories", max_value=5000),
        "protein_g": require_number(body, "protein_g", max_value=500),
    }


def validate_sleep(body):
    """Sleep is logged against the date you WOKE UP.

    So a night from 11pm on the 10th to 7am on the 11th counts toward the 11th.
    """
    return {
        "date": parse_date(body.get("date")),
        "hours": require_number(body, "hours", max_value=24),
    }


def validate_workout(body):
    """One exercise, e.g. bench press 3 sets x 8 reps at 135.

    'weight' has no unit on purpose: use lb or kg, just be consistent.
    """
    return {
        "date": parse_date(body.get("date")),
        "exercise": require_text(body, "exercise", 60, "Bench press"),
        "sets": require_number(body, "sets", max_value=50),
        "reps": require_number(body, "reps", max_value=1000),
        "weight": require_number(body, "weight", max_value=2000),
    }


def validate_goals(body):
    goals = {
        "calories": require_number(body, "calories", max_value=10000),
        "protein_g": require_number(body, "protein_g", max_value=1000),
        "sleep_hours": require_number(body, "sleep_hours", max_value=24),
        "reminders": body.get("reminders", True),
        "utc_offset_minutes": body.get("utc_offset_minutes", 0),
    }
    if not isinstance(goals["reminders"], bool):
        raise ValidationError("'reminders' must be true or false.")
    offset = goals["utc_offset_minutes"]
    if isinstance(offset, bool) or not isinstance(offset, int) or not -840 <= offset <= 840:
        raise ValidationError("'utc_offset_minutes' must be a whole number between -840 and 840.")
    return goals


def validate_meal_text(body):
    return require_text(body, "text", 300, "3 eggs and a slice of toast")


def validate_days(value):
    """Used by GET /insights?days=7. Query strings always arrive as text."""
    if value is None:
        return 7
    if not str(value).isdigit() or not 1 <= int(value) <= 90:
        raise ValidationError("'days' must be a whole number from 1 to 90.")
    return int(value)


# ---------- Daily math ----------

def workout_volume(workouts):
    """Total volume = sets x reps x weight, added up over all exercises."""
    return sum(w["sets"] * w["reps"] * w["weight"] for w in workouts)


def summarize_day(meals, sleep, goals):
    """Add up a day's meals and sleep, then compare them with the goals.

    'remaining' = goal - total, so a negative number means you went past it.
    """
    totals = {
        "calories": sum(meal["calories"] for meal in meals),
        "protein_g": sum(meal["protein_g"] for meal in meals),
        "sleep_hours": sleep["hours"] if sleep else 0,
    }

    if not goals:
        return {"totals": totals, "goals": None, "remaining": None}

    return {
        "totals": totals,
        "goals": goals,
        "remaining": {key: goals[key] - totals[key] for key in totals},
        "protein_goal_met": totals["protein_g"] >= goals["protein_g"],
        "sleep_goal_met": totals["sleep_hours"] >= goals["sleep_hours"],
    }


# ---------- Multi-day insights ----------

def _average(values):
    return round(sum(values) / len(values), 1) if values else None


def build_insights(days_by_date, goals, start, end):
    """Summarize a date range, e.g. the last 7 days.

    days_by_date looks like {"2026-10-11": {"meals": [...], "sleep": {...}, "workouts": [...]}}.
    Days with nothing logged can simply be missing.
    """
    sleep_target = goals["sleep_hours"] if goals else 7
    protein_target = goals["protein_g"] if goals else None

    daily = []
    current = date.fromisoformat(start)
    while current <= date.fromisoformat(end):
        day = days_by_date.get(current.isoformat(), {})
        meals = day.get("meals", [])
        sleep = day.get("sleep")
        daily.append({
            "date": current.isoformat(),
            "protein_g": sum(m["protein_g"] for m in meals) if meals else None,
            "sleep_hours": sleep["hours"] if sleep else None,
            "volume": workout_volume(day.get("workouts", [])),
        })
        current += timedelta(days=1)

    protein_days = [d["protein_g"] for d in daily if d["protein_g"] is not None]
    sleep_nights = [d["sleep_hours"] for d in daily if d["sleep_hours"] is not None]
    workout_days = [d for d in daily if d["volume"] > 0]

    # The question we care about: do I train harder after a good night's sleep?
    # Only workout days with sleep logged that morning can answer it.
    after_good = [d["volume"] for d in workout_days
                  if d["sleep_hours"] is not None and d["sleep_hours"] >= sleep_target]
    after_short = [d["volume"] for d in workout_days
                   if d["sleep_hours"] is not None and d["sleep_hours"] < sleep_target]

    return {
        "start": start,
        "end": end,
        "daily": daily,
        "avg_protein_g": _average(protein_days),
        "protein_goal_days": (sum(1 for p in protein_days if p >= protein_target)
                              if protein_target is not None else None),
        "days_with_meals": len(protein_days),
        "avg_sleep_hours": _average(sleep_nights),
        "sleep_goal_nights": sum(1 for s in sleep_nights if s >= sleep_target),
        "nights_logged": len(sleep_nights),
        "workout_days": len(workout_days),
        "avg_volume_after_good_sleep": _average(after_good),
        "avg_volume_after_short_sleep": _average(after_short),
        "sleep_target": sleep_target,
    }


# ---------- Time zones and email text ----------

def local_date(now_utc, utc_offset_minutes):
    """Today's date for the user, given the offset their browser reported.

    The stored offset can be an hour off after a daylight-saving change, but
    reminders run in the evening, so being an hour off never changes the date.
    """
    return (now_utc + timedelta(minutes=utc_offset_minutes)).date().isoformat()


def build_reminder(summary, sleep_logged):
    """Return the evening reminder text, or None if there's nothing to say."""
    lines = []
    if summary.get("remaining") and summary["remaining"]["protein_g"] > 0:
        got = summary["totals"]["protein_g"]
        goal = summary["goals"]["protein_g"]
        lines.append(f"You're {summary['remaining']['protein_g']}g short of your protein "
                     f"goal today ({got}g of {goal}g).")
    if not sleep_logged:
        lines.append("You haven't logged last night's sleep yet.")
    return "\n".join(lines) if lines else None


def format_weekly_email(insights):
    lines = [f"Your week: {insights['start']} to {insights['end']}", ""]

    if insights["days_with_meals"]:
        lines.append(f"Protein: averaged {insights['avg_protein_g']}g on the "
                     f"{insights['days_with_meals']} days you logged meals.")
        if insights["protein_goal_days"] is not None:
            lines.append(f"You hit your protein goal on {insights['protein_goal_days']} of them.")
    else:
        lines.append("No meals logged this week.")

    if insights["nights_logged"]:
        lines.append(f"Sleep: averaged {insights['avg_sleep_hours']} hours; "
                     f"{insights['sleep_goal_nights']} of {insights['nights_logged']} nights "
                     f"reached {insights['sleep_target']} hours.")
    else:
        lines.append("No sleep logged this week.")

    lines.append(f"Workouts: {insights['workout_days']} training days.")
    good, short = insights["avg_volume_after_good_sleep"], insights["avg_volume_after_short_sleep"]
    if good is not None and short is not None:
        lines.append(f"Average volume after a full night's sleep: {good}. "
                     f"After a short night: {short}.")
    return "\n".join(lines)


def utc_now():
    """Wrapped in a function so it's easy to see where 'now' comes from."""
    return datetime.now(timezone.utc)

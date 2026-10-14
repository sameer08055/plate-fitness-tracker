"""
All DynamoDB access lives here (single-table design).

Every item for a user shares one partition key (PK). The sort key (SK)
says what the item is:

    PK                  SK
    USER#<id>           GOALS
    USER#<id>           DAY#2026-10-11#MEAL#<uuid>
    USER#<id>           DAY#2026-10-11#WORKOUT#<uuid>
    USER#<id>           DAY#2026-10-11#SLEEP
    CACHE#<source>      <lookup key>        (cached food lookups, auto-deleted by TTL)

Since everything for one day starts with "DAY#<date>#", a single Query
with begins_with() fetches a whole day, and between() fetches a date range.
"""
import json
import os
import time
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key

# Created once per Lambda container and reused across "warm" invocations,
# which saves time on every request after the first.
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])

CACHE_DAYS = 30


def _user_pk(user_id):
    return f"USER#{user_id}"


def _strip_keys(item):
    """Remove PK/SK so API responses only contain the user's data."""
    return {k: v for k, v in item.items() if k not in ("PK", "SK")}


def _new_entry(user_id, day, kind, data):
    """Build a meal or workout item with a fresh id and timestamp."""
    entry_id = str(uuid.uuid4())
    return {
        "PK": _user_pk(user_id),
        "SK": f"DAY#{day}#{kind}#{entry_id}",
        "id": entry_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        **data,
    }


# ---------- Goals ----------

def save_goals(user_id, goals):
    table.put_item(Item={"PK": _user_pk(user_id), "SK": "GOALS", **goals})


def get_goals(user_id):
    response = table.get_item(Key={"PK": _user_pk(user_id), "SK": "GOALS"})
    item = response.get("Item")
    return _strip_keys(item) if item else None


# ---------- Meals, workouts, sleep ----------

def add_meal(user_id, meal):
    item = _new_entry(user_id, meal["date"], "MEAL", meal)
    table.put_item(Item=item)
    return _strip_keys(item)


def add_workout(user_id, workout):
    item = _new_entry(user_id, workout["date"], "WORKOUT", workout)
    table.put_item(Item=item)
    return _strip_keys(item)


def delete_entry(user_id, day, kind, entry_id):
    """kind is "MEAL" or "WORKOUT"."""
    table.delete_item(Key={"PK": _user_pk(user_id), "SK": f"DAY#{day}#{kind}#{entry_id}"})


def save_sleep(user_id, sleep):
    # One sleep entry per day: logging again simply overwrites it.
    item = {"PK": _user_pk(user_id), "SK": f"DAY#{sleep['date']}#SLEEP", **sleep}
    table.put_item(Item=item)
    return _strip_keys(item)


def _group_by_day(items):
    """Turn raw items into {"2026-10-11": {"meals": [], "workouts": [], "sleep": None}}."""
    days = {}
    for item in items:
        _, day, kind, *_ = item["SK"].split("#")
        bucket = days.setdefault(day, {"meals": [], "workouts": [], "sleep": None})
        if kind == "MEAL":
            bucket["meals"].append(_strip_keys(item))
        elif kind == "WORKOUT":
            bucket["workouts"].append(_strip_keys(item))
        elif kind == "SLEEP":
            bucket["sleep"] = _strip_keys(item)

    for bucket in days.values():
        bucket["meals"].sort(key=lambda m: m["logged_at"])
        bucket["workouts"].sort(key=lambda w: w["logged_at"])
    return days


def _query_all(**kwargs):
    """Run a Query and follow LastEvaluatedKey, since each call returns at most 1 MB."""
    items = []
    while True:
        response = table.query(**kwargs)
        items.extend(response["Items"])
        if "LastEvaluatedKey" not in response:
            return items
        kwargs["ExclusiveStartKey"] = response["LastEvaluatedKey"]


def get_day(user_id, day):
    """Everything logged on one day, in one Query."""
    items = _query_all(
        KeyConditionExpression=Key("PK").eq(_user_pk(user_id))
        & Key("SK").begins_with(f"DAY#{day}#")
    )
    return _group_by_day(items).get(day, {"meals": [], "workouts": [], "sleep": None})


def get_range(user_id, start, end):
    """Everything logged from start to end (inclusive), in one Query.

    "~" sorts after every character we use in sort keys, so
    "DAY#<end>#~" is just past the last item of the end date.
    """
    items = _query_all(
        KeyConditionExpression=Key("PK").eq(_user_pk(user_id))
        & Key("SK").between(f"DAY#{start}#", f"DAY#{end}#~")
    )
    return _group_by_day(items)


# ---------- Cache for food lookups ----------

def cache_get(source, key):
    response = table.get_item(Key={"PK": f"CACHE#{source}", "SK": key})
    item = response.get("Item")
    # TTL deletion can lag by a day or two, so check the expiry ourselves too.
    if not item or item["expires_at"] < time.time():
        return None
    return json.loads(item["data"])


def cache_put(source, key, data):
    # Stored as a JSON string so floats don't need converting to Decimal.
    table.put_item(Item={
        "PK": f"CACHE#{source}",
        "SK": key,
        "data": json.dumps(data),
        "expires_at": int(time.time()) + CACHE_DAYS * 86400,
    })

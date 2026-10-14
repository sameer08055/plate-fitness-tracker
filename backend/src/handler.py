"""
Lambda entry point for the API.

API Gateway (HTTP API, payload format 2.0) checks the login token, then
sends every request to lambda_handler(). We read event["routeKey"]
(e.g. "POST /meals") and call the matching function from ROUTES below.
"""
import base64
import json
import logging
import re
from datetime import date, timedelta
from decimal import Decimal

import ai
import db
import nutrition
from logic import (
    ValidationError,
    build_insights,
    parse_date,
    summarize_day,
    validate_days,
    validate_goals,
    validate_meal,
    validate_meal_text,
    validate_sleep,
    validate_workout,
    workout_volume,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)


# ---------- Helpers ----------

def get_user_id(event):
    """API Gateway already verified the Cognito token, so we can trust its claims.
    'sub' is the user's permanent, unique ID."""
    return event["requestContext"]["authorizer"]["jwt"]["claims"]["sub"]


def read_body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        # parse_float=Decimal because DynamoDB rejects Python floats.
        body = json.loads(raw, parse_float=Decimal)
    except json.JSONDecodeError:
        raise ValidationError("Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise ValidationError("Request body must be a JSON object.")
    return body


def query_param(event, name):
    return (event.get("queryStringParameters") or {}).get(name)


def decimal_to_number(value):
    """json.dumps can't handle Decimal, so turn it back into int or float."""
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"Cannot convert {type(value)} to JSON")


def respond(status_code, data):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(data, default=decimal_to_number),
    }


# ---------- Goals ----------

def put_goals(event, user_id):
    goals = validate_goals(read_body(event))
    db.save_goals(user_id, goals)
    return respond(200, goals)


def get_goals(event, user_id):
    goals = db.get_goals(user_id)
    if goals is None:
        return respond(404, {"error": "No goals set yet."})
    return respond(200, goals)


# ---------- Logging meals, sleep, workouts ----------

def post_meal(event, user_id):
    return respond(201, db.add_meal(user_id, validate_meal(read_body(event))))


def post_workout(event, user_id):
    return respond(201, db.add_workout(user_id, validate_workout(read_body(event))))


def post_sleep(event, user_id):
    return respond(200, db.save_sleep(user_id, validate_sleep(read_body(event))))


def delete_meal(event, user_id):
    return _delete(event, user_id, "MEAL")


def delete_workout(event, user_id):
    return _delete(event, user_id, "WORKOUT")


def _delete(event, user_id, kind):
    params = event["pathParameters"]
    db.delete_entry(user_id, parse_date(params["date"]), kind, params["id"])
    return respond(200, {"deleted": params["id"]})


# ---------- Reading data back ----------

def get_day(event, user_id):
    day = parse_date(event["pathParameters"]["date"])
    entries = db.get_day(user_id, day)
    summary = summarize_day(entries["meals"], entries["sleep"], db.get_goals(user_id))
    return respond(200, {
        "date": day,
        **entries,
        **summary,
        "workout_volume": workout_volume(entries["workouts"]),
    })


def get_insights(event, user_id):
    # The browser sends its own local date as 'end', so "this week" matches
    # the user's time zone rather than the server's.
    end = parse_date(query_param(event, "end"))
    days = validate_days(query_param(event, "days"))
    start = (date.fromisoformat(end) - timedelta(days=days - 1)).isoformat()
    data = db.get_range(user_id, start, end)
    return respond(200, build_insights(data, db.get_goals(user_id), start, end))


# ---------- Food lookups ----------

def search_foods(event, user_id):
    query = query_param(event, "q") or ""
    if not 2 <= len(query.strip()) <= 80:
        raise ValidationError("Search for 2 to 80 characters, e.g. ?q=chicken breast")
    return respond(200, {"results": nutrition.search_foods(query)})


def get_barcode(event, user_id):
    code = event["pathParameters"]["code"]
    if not re.fullmatch(r"\d{8,14}", code):
        raise ValidationError("A barcode is 8 to 14 digits.")
    product = nutrition.lookup_barcode(code)
    if product is None:
        return respond(404, {"error": "That barcode isn't in Open Food Facts. Enter the food manually."})
    return respond(200, product)


def parse_meal(event, user_id):
    """Describe a meal in words -> foods, grams, calories, protein.

    Nothing is saved here. The app shows the result so you can check it,
    then saves it with POST /meals.
    """
    text = validate_meal_text(read_body(event))
    items = []
    for guess in ai.parse_meal_text(text):
        matches = nutrition.search_foods(guess["food"], limit=1)
        match = matches[0] if matches else None
        items.append({
            **guess,
            "matched_name": match["name"] if match else None,
            **(nutrition.scale(match, guess["grams"]) if match else {"calories": 0, "protein_g": 0}),
        })
    return respond(200, {
        "text": text,
        "items": items,
        "calories": sum(i["calories"] for i in items),
        "protein_g": round(sum(i["protein_g"] for i in items), 1),
    })


# Must match the routes in infra/api.tf.
ROUTES = {
    "PUT /goals": put_goals,
    "GET /goals": get_goals,
    "POST /meals": post_meal,
    "POST /meals/parse": parse_meal,
    "DELETE /days/{date}/meals/{id}": delete_meal,
    "POST /workouts": post_workout,
    "DELETE /days/{date}/workouts/{id}": delete_workout,
    "POST /sleep": post_sleep,
    "GET /days/{date}": get_day,
    "GET /insights": get_insights,
    "GET /foods/search": search_foods,
    "GET /barcode/{code}": get_barcode,
}


def lambda_handler(event, context):
    route = event.get("routeKey")
    handler = ROUTES.get(route)
    if handler is None:
        return respond(404, {"error": f"Unknown route: {route}"})

    try:
        return handler(event, get_user_id(event))
    except ValidationError as error:
        return respond(400, {"error": str(error)})
    except ai.AiParseError as error:
        return respond(422, {"error": f"{error} Try something like \"2 eggs and 1 cup of rice\"."})
    except nutrition.NutritionServiceError:
        logger.exception("Food database error on %s", route)
        return respond(502, {"error": "The food database didn't respond. Try again, or enter the meal manually."})
    except Exception:
        # Full stack trace goes to CloudWatch Logs; the client gets a safe message.
        logger.exception("Unhandled error on route %s", route)
        return respond(500, {"error": "Something went wrong on the server."})

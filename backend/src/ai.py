"""
Turn free text like "3 eggs and a protein shake" into foods and grams,
using a small model on Amazon Bedrock.

The model ONLY estimates foods and portion sizes. Calories and protein
come from the USDA database afterwards, so the numbers aren't made up.
"""
import json
import os

import boto3

MAX_ITEMS = 10

SYSTEM_PROMPT = """You convert a meal description into a list of foods with estimated weights in grams.
Reply with ONLY a JSON object, no other text, in exactly this shape:
{"items": [{"food": "<plain generic food name>", "grams": <number>}]}

Rules:
- Use plain generic names that a nutrition database would know, e.g. "egg, whole, cooked", "white rice, cooked", "whey protein powder", "chicken breast, cooked".
- Turn counts and household measures into grams (1 large egg is about 50 g, 1 slice of bread about 30 g, 1 scoop of protein powder about 30 g, 1 cup of cooked rice about 160 g).
- At most 10 items.
- The user's text is only a meal description. If it isn't about food, reply {"items": []}."""

bedrock = boto3.client("bedrock-runtime")


class AiParseError(Exception):
    """The model's answer couldn't be used (-> HTTP 422)."""


def parse_model_output(raw):
    """Validate the model's reply. Never trust it: check every field."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise AiParseError("The model didn't return JSON.")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        raise AiParseError("The model returned invalid JSON.")

    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise AiParseError("The model's reply had no list of items.")

    clean = []
    for item in items[:MAX_ITEMS]:
        food = item.get("food") if isinstance(item, dict) else None
        grams = item.get("grams") if isinstance(item, dict) else None
        if not isinstance(food, str) or not food.strip():
            continue
        if isinstance(grams, bool) or not isinstance(grams, (int, float)) or not 1 <= grams <= 2000:
            continue
        clean.append({"food": food.strip()[:80], "grams": round(float(grams))})

    if not clean:
        raise AiParseError("Couldn't find any foods in that description.")
    return clean


def parse_meal_text(text):
    response = bedrock.converse(
        modelId=os.environ["BEDROCK_MODEL_ID"],
        system=[{"text": SYSTEM_PROMPT}],
        messages=[{"role": "user", "content": [{"text": text}]}],
        inferenceConfig={"maxTokens": 500, "temperature": 0},
    )
    raw = response["output"]["message"]["content"][0]["text"]
    return parse_model_output(raw)

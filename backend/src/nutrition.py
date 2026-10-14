"""
Food lookups from two free databases, with results cached in DynamoDB.

- USDA FoodData Central: generic foods ("chicken breast"), values per 100 g.
- Open Food Facts: packaged foods by barcode.

The extract_* functions are pure (no network), so they're unit tested
with sample responses.
"""
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

import db

USDA_SEARCH_URL = "https://api.nal.usda.gov/fdc/v1/foods/search"
OFF_PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"


class NutritionServiceError(Exception):
    """An outside food database didn't answer properly (-> HTTP 502)."""


def _http_json(url, data=None, headers=None):
    request = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=6) as response:
            return json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise NutritionServiceError(f"Request to {urllib.parse.urlparse(url).netloc} failed: {error}")


def normalize_query(text):
    """'  Chicken   Breast ' -> 'chicken breast', so cache keys match."""
    return re.sub(r"\s+", " ", text.strip().lower())[:80]


def scale(per_100g, grams):
    """Nutrition for a portion, from per-100 g values."""
    factor = grams / 100
    return {
        "calories": round(per_100g["calories_per_100g"] * factor),
        "protein_g": round(per_100g["protein_per_100g"] * factor, 1),
    }


# ---------- USDA ----------

# USDA identifies nutrients by number. Energy can be listed under a few
# numbers depending on the dataset, so we try them in order.
ENERGY_KCAL_NUMBERS = ["208", "957", "958"]
PROTEIN_NUMBER = "203"


def extract_usda_food(food):
    """Turn one USDA search result into our format, or None if data is missing."""
    by_number = {}
    for nutrient in food.get("foodNutrients", []):
        number = str(nutrient.get("nutrientNumber", ""))
        unit = str(nutrient.get("unitName", "")).upper()
        if number in ENERGY_KCAL_NUMBERS and unit != "KCAL":
            continue  # skip kilojoule entries
        by_number.setdefault(number, nutrient.get("value"))

    calories = next((by_number[n] for n in ENERGY_KCAL_NUMBERS if by_number.get(n) is not None), None)
    protein = by_number.get(PROTEIN_NUMBER)
    if calories is None or protein is None:
        return None

    return {
        "source": "usda",
        "id": str(food.get("fdcId")),
        "name": food.get("description", "Unknown food").capitalize(),
        "calories_per_100g": float(calories),
        "protein_per_100g": float(protein),
    }


def search_foods(query, limit=5):
    query = normalize_query(query)
    if not query:
        return []

    cached = db.cache_get("usda", query)
    if cached is not None:
        return cached[:limit]

    response = _http_json(
        f"{USDA_SEARCH_URL}?api_key={urllib.parse.quote(os.environ['USDA_API_KEY'])}",
        # Foundation and SR Legacy are USDA's lab-measured generic foods,
        # which give cleaner matches than thousands of branded products.
        data={"query": query, "dataType": ["Foundation", "SR Legacy"], "pageSize": 10},
    )
    results = [f for f in map(extract_usda_food, response.get("foods", [])) if f]
    db.cache_put("usda", query, results)
    return results[:limit]


# ---------- Open Food Facts (barcodes) ----------

def extract_off_product(code, payload):
    """Turn an Open Food Facts response into our format, or None if unusable."""
    product = payload.get("product") or {}
    nutriments = product.get("nutriments") or {}
    calories = nutriments.get("energy-kcal_100g")
    protein = nutriments.get("proteins_100g")
    if payload.get("status") != 1 or calories is None or protein is None:
        return None

    serving = product.get("serving_quantity")
    return {
        "source": "barcode",
        "id": code,
        "name": product.get("product_name") or f"Product {code}",
        "calories_per_100g": float(calories),
        "protein_per_100g": float(protein),
        "serving_g": float(serving) if serving else None,
    }


def lookup_barcode(code):
    cached = db.cache_get("barcode", code)
    if cached is not None:
        return cached or None  # we cache "not found" as {} too

    # Open Food Facts asks apps to identify themselves in the User-Agent.
    contact = os.environ.get("CONTACT_EMAIL", "unknown")
    payload = _http_json(
        OFF_PRODUCT_URL.format(code=code) + "?fields=product_name,nutriments,serving_quantity",
        headers={"User-Agent": f"FitnessTrackerStudentProject/1.0 ({contact})"},
    )
    product = extract_off_product(code, payload)
    db.cache_put("barcode", code, product or {})
    return product

"""Tests for reading USDA and Open Food Facts responses (no network calls)."""
from nutrition import extract_off_product, extract_usda_food, normalize_query, scale

USDA_FOOD = {
    "fdcId": 171477,
    "description": "CHICKEN BREAST, COOKED",
    "foodNutrients": [
        {"nutrientNumber": "203", "unitName": "G", "value": 31.0},
        {"nutrientNumber": "208", "unitName": "KCAL", "value": 165},
        {"nutrientNumber": "268", "unitName": "kJ", "value": 690},
    ],
}


def test_usda_food_is_extracted():
    food = extract_usda_food(USDA_FOOD)
    assert food["name"] == "Chicken breast, cooked"
    assert food["calories_per_100g"] == 165
    assert food["protein_per_100g"] == 31


def test_usda_energy_falls_back_to_atwater_number():
    food = {"fdcId": 1, "description": "x", "foodNutrients": [
        {"nutrientNumber": "203", "unitName": "G", "value": 10},
        {"nutrientNumber": "957", "unitName": "KCAL", "value": 120},
    ]}
    assert extract_usda_food(food)["calories_per_100g"] == 120


def test_usda_food_without_protein_is_skipped():
    food = {"fdcId": 1, "description": "x", "foodNutrients": [
        {"nutrientNumber": "208", "unitName": "KCAL", "value": 100}]}
    assert extract_usda_food(food) is None


def test_scale_to_portion():
    food = extract_usda_food(USDA_FOOD)
    assert scale(food, 200) == {"calories": 330, "protein_g": 62.0}


def test_barcode_product_is_extracted():
    payload = {"status": 1, "product": {
        "product_name": "Greek yogurt", "serving_quantity": 170,
        "nutriments": {"energy-kcal_100g": 59, "proteins_100g": 10.3}}}
    product = extract_off_product("0123456789012", payload)
    assert product["name"] == "Greek yogurt"
    assert product["serving_g"] == 170


def test_unknown_barcode_returns_none():
    assert extract_off_product("0000", {"status": 0}) is None


def test_query_normalized_for_cache():
    assert normalize_query("  Chicken   BREAST ") == "chicken breast"

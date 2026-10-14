"""Tests for validating the AI model's output (no AWS calls)."""
import pytest

from ai import AiParseError, parse_model_output


def test_clean_json_is_parsed():
    raw = '{"items": [{"food": "egg, whole, cooked", "grams": 150}]}'
    assert parse_model_output(raw) == [{"food": "egg, whole, cooked", "grams": 150}]


def test_json_wrapped_in_text_is_found():
    raw = 'Here you go:\n```json\n{"items": [{"food": "white rice, cooked", "grams": 160.4}]}\n```'
    assert parse_model_output(raw) == [{"food": "white rice, cooked", "grams": 160}]


def test_bad_items_are_dropped():
    raw = '{"items": [{"food": "", "grams": 50}, {"food": "toast", "grams": -3}, {"food": "oats", "grams": 40}]}'
    assert parse_model_output(raw) == [{"food": "oats", "grams": 40}]


def test_no_foods_is_an_error():
    with pytest.raises(AiParseError):
        parse_model_output('{"items": []}')


def test_not_json_is_an_error():
    with pytest.raises(AiParseError):
        parse_model_output("I can't help with that.")

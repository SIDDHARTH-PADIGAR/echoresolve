import json
from unittest.mock import patch

from echoresolve.llm_router import route_intent


def test_router_accepts_valid_model_intent():
    response = json.dumps({"intent": "check_balance"})
    mock_response = {"response": response}

    with patch("echoresolve.llm_router.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = (
            json.dumps(mock_response).encode("utf-8")
        )
        result = route_intent("What is my balance?")

    assert result["intent"] == "check_balance"
    assert result["fallback"] is False


def test_router_falls_back_when_ollama_is_unavailable():
    with patch(
        "echoresolve.llm_router.urllib.request.urlopen",
        side_effect=OSError("Ollama unavailable"),
    ):
        result = route_intent("What is my balance?")

    assert result["intent"] == "clarify"
    assert result["fallback"] is True


def test_router_rejects_invalid_model_intent():
    mock_response = {"response": '{"intent":"delete_account"}'}

    with patch("echoresolve.llm_router.urllib.request.urlopen") as urlopen:
        urlopen.return_value.__enter__.return_value.read.return_value = (
            json.dumps(mock_response).encode("utf-8")
        )
        result = route_intent("Delete my account")

    assert result["intent"] == "clarify"
    assert result["fallback"] is True


def test_empty_message_routes_to_clarification_without_model_call():
    with patch("echoresolve.llm_router.urllib.request.urlopen") as urlopen:
        result = route_intent("   ")

    assert result["intent"] == "clarify"
    assert urlopen.called is False

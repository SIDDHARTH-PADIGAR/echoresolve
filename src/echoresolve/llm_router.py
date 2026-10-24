import json
import urllib.error
import urllib.request
from typing import Any

MODEL = "llama3.2:1b"
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"

ALLOWED_INTENTS = {
    "check_balance",
    "account_context",
    "propose_payment",
    "confirm_payment",
    "clarify",
}


def route_intent(message: str) -> dict[str, Any]:
    """Classify a borrower message; never execute tools or authorize payments."""
    if not message.strip():
        return {"intent": "clarify", "reason": "empty_message", "model": MODEL}

    prompt = (
        "Classify the borrower message into exactly one intent:\n"
        "check_balance, account_context, propose_payment, confirm_payment, clarify.\n"
        "Use clarify if uncertain. Do not answer the borrower or invent facts.\n"
        'Return only a JSON object with one key: "intent".\n'
        f"Borrower message: {message[:2000]}\n"
        'JSON: {"intent":'
    )

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "format": {
            "type": "object",
            "properties": {
                "intent": {
                    "type": "string",
                    "enum": sorted(ALLOWED_INTENTS),
                }
            },
            "required": ["intent"],
            "additionalProperties": False,
        },
        "options": {
            "num_predict": 32,
            "temperature": 0,
        },
    }

    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))
        parsed = json.loads(result.get("response", ""))
        intent = parsed.get("intent")
        if intent not in ALLOWED_INTENTS:
            raise ValueError("Model returned an unsupported intent")
        return {"intent": intent, "model": MODEL, "fallback": False}
    except (
        urllib.error.URLError,
        OSError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
    ):
        return {
            "intent": "clarify",
            "reason": "router_unavailable_or_invalid_output",
            "model": MODEL,
            "fallback": True,
        }


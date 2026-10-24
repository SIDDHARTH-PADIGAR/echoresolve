import re
from datetime import date
from decimal import Decimal
from typing import Any

_DOLLAR_AMOUNT = re.compile(r"(?<!\w)[$]\s*(\d+(?:\.\d{1,2})?)(?!\w)")
_CURRENCY_AMOUNT = re.compile(
    r"(?<![\w.])(\d+(?:\.\d{1,2})?)\s*(?:USD|dollars?)(?!\w)",
    re.IGNORECASE,
)
_DATE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


def extract_payment_details(message: str) -> dict[str, Any]:
    text = message[:2000]
    amounts = [
        int(Decimal(m.group(1)) * 100)
        for m in _DOLLAR_AMOUNT.finditer(text)
    ]
    amounts += [
        int(Decimal(m.group(1)) * 100)
        for m in _CURRENCY_AMOUNT.finditer(text)
    ]
    dates = _DATE.findall(text)

    if len(amounts) != 1 or amounts[0] <= 0:
        return {"ok": False, "reason": "Please state one unambiguous positive amount, such as $50."}
    if len(dates) != 1:
        return {"ok": False, "reason": "Please state one due date in YYYY-MM-DD format."}

    try:
        parsed_date = date.fromisoformat(dates[0])
    except ValueError:
        return {"ok": False, "reason": "That date is invalid. Please use YYYY-MM-DD."}

    return {
        "ok": True,
        "amount_cents": amounts[0],
        "due_date": parsed_date.isoformat(),
    }

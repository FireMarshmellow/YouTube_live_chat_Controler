import threading
import time

import requests

# Free daily rates, no API key (https://www.exchangerate-api.com/docs/free)
RATES_URL = "https://open.er-api.com/v6/latest/GBP"
RATES_MAX_AGE = 6 * 60 * 60   # seconds before rates are refreshed
RETRY_AFTER_FAILURE = 5 * 60  # seconds before trying again after a failed fetch

_rates: dict = {}  # { currency code: units per £1 }
_fetched_at = 0.0
_last_attempt = 0.0
_lock = threading.Lock()


def _refresh_rates() -> None:
    global _rates, _fetched_at, _last_attempt
    _last_attempt = time.monotonic()
    try:
        data = requests.get(RATES_URL, timeout=5).json()
        if data.get("result") != "success":
            print(f"Exchange rate fetch failed: {data.get('error-type', data)}")
            return
        _rates = data["rates"]
        _fetched_at = time.monotonic()
    except Exception as exc:
        print(f"Couldn't fetch exchange rates: {exc}")


def preload_rates() -> None:
    """Fetch rates ahead of the first Super Chat so it isn't delayed."""
    with _lock:
        _refresh_rates()


def to_gbp(amount: float, currency: str) -> float | None:
    """Convert an amount to pounds, or None if no rate is available."""
    currency = (currency or "").upper()
    if currency == "GBP":
        return amount
    with _lock:
        now = time.monotonic()
        stale = not _rates or now - _fetched_at > RATES_MAX_AGE
        if stale and now - _last_attempt > RETRY_AFTER_FAILURE:
            _refresh_rates()
        rate = _rates.get(currency)
    return amount / rate if rate else None


def format_gbp(amount: float) -> str:
    """£1.50, or £5 for whole pounds."""
    amount = round(amount, 2)
    return f"£{amount:,.0f}" if amount == int(amount) else f"£{amount:,.2f}"

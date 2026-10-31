"""Credit accounting: the usage.jsonl log, measured prices, and the budget guard.

No price is assumed as fact. Dialogue starts from Step 0's model rate (labelled as an assumption);
SFX and music start unknown, so their first call is a price probe estimated pessimistically.
Every paid call reads the account balance before and after, and the measured price replaces
the estimate from then on.
"""
import json
from datetime import datetime

from core.config import RESERVE_CREDITS, SPEND_CAP_CREDITS

# Deliberately pessimistic stand-in for a feature whose price is not known yet. It only decides
# whether a probe call is allowed; it is replaced by the measured price after that call.
UNKNOWN_PRICE_ALLOWANCE_CREDITS = 1000
FEATURES = ("dialogue", "flat", "sfx", "ambience", "music")


class BudgetError(RuntimeError):
    pass


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_usage(path):
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def append_usage(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def credits_spent(rows):
    """Credits charged so far: measured where known, else estimated. Cache hits and samples cost 0."""
    total = 0
    for r in rows:
        if r.get("cache_hit") or r.get("sample"):
            continue
        cost = r.get("credits_actual") if r.get("credits_actual") is not None else r.get("credits_estimated")
        total += cost or 0
    return total


def load_prices(path):
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_prices(path, prices):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(prices, indent=2), encoding="utf-8")


def estimate(feature, chars, prices):
    """Return (credits, basis). Dialogue and flat are per character; the rest are per call."""
    if feature in ("dialogue", "flat"):
        rate = prices.get("dialogue_credits_per_char")
        if rate is None:
            return UNKNOWN_PRICE_ALLOWANCE_CREDITS, "unknown price (probe)"
        return round(chars * rate), prices.get("dialogue_basis", "measured")
    per_call = prices.get(f"{feature}_credits_per_call")
    if per_call is None:
        return UNKNOWN_PRICE_ALLOWANCE_CREDITS, "unknown price (probe)"
    return round(per_call), "measured"


def record_price(prices, feature, chars, credits_actual):
    """Update measured prices from one call. Keeps the higher rate, so estimates never get optimistic."""
    if not credits_actual or credits_actual <= 0:
        return prices
    if feature in ("dialogue", "flat") and chars:
        rate = credits_actual / chars
        if rate > (prices.get("dialogue_credits_per_char") or 0) or prices.get("dialogue_basis") != "measured":
            prices["dialogue_credits_per_char"] = rate
            prices["dialogue_basis"] = "measured"
    elif feature not in ("dialogue", "flat"):
        key = f"{feature}_credits_per_call"
        prices[key] = max(credits_actual, prices.get(key) or 0)
    return prices


def check_budget(spent, next_estimate, account_remaining=None):
    """Refuse a call that could break the spend cap or eat into the reserve."""
    if spent + next_estimate > SPEND_CAP_CREDITS:
        raise BudgetError(f"stop: {spent} spent + {next_estimate} estimated would exceed the "
                          f"{SPEND_CAP_CREDITS}-credit cap (10,000 budget minus {RESERVE_CREDITS} reserve)")
    if account_remaining is not None and account_remaining - next_estimate < RESERVE_CREDITS:
        raise BudgetError(f"stop: account has {account_remaining} credits left; spending ~{next_estimate} "
                          f"would go below the {RESERVE_CREDITS}-credit reserve")

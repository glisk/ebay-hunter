"""
Automatic discard filter logic.

Each filter function returns (True, reason_str) if the item should be
discarded, or (False, "") if it passes.

apply_filters() runs all checks and returns the discard decision plus
a human-readable reason for logging/debugging.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# CPUs that flag a 3000-series machine (hard discard)
CPU_3000_SERIES = ["3945WX", "3955WX", "3975WX", "3995WX", "3000WX"]

# 5000-series CPUs we actively want
CPU_5000_SERIES = ["5945WX", "5955WX", "5965WX", "5975WX", "5995WX"]

# 5995WX is ok only if the price is a genuine anomaly
CPU_5995WX_PRICE_THRESHOLD = 1200.0

# Conditions considered "for parts / not working"
PARTS_CONDITIONS = {
    "FOR_PARTS_OR_NOT_WORKING",
    "FOR PARTS OR NOT WORKING",
    "FOR_PARTS",
    "PARTS ONLY",
}

# Seller feedback thresholds
FEEDBACK_MIN_PCT = 95.0
FEEDBACK_MIN_SCORE = 10

# Minimum hours remaining on pure auctions before they're discardable
AUCTION_MIN_HOURS = 12


def _title_upper(item: dict[str, Any]) -> str:
    return item.get("title", "").upper()


def _description_upper(item: dict[str, Any]) -> str:
    return item.get("short_description", "").upper()


def _text_upper(item: dict[str, Any]) -> str:
    return _title_upper(item) + " " + _description_upper(item)


# ---------------------------------------------------------------------------
# Individual filter predicates
# ---------------------------------------------------------------------------

def _filter_3000_series(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard if any 3000-series Threadripper PRO CPU is mentioned."""
    text = _text_upper(item)
    for cpu in CPU_3000_SERIES:
        if cpu in text:
            return True, f"3000-series CPU detected ({cpu})"
    return False, ""


def _filter_parts_condition(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard if the listing condition indicates 'for parts / not working'."""
    condition = item.get("condition", "").upper().replace("-", "_").replace(" ", "_")
    if condition in {c.upper().replace(" ", "_") for c in PARTS_CONDITIONS}:
        return True, f"Condition is 'for parts/not working' ({item.get('condition')})"
    # Also scan title/description text
    text = _text_upper(item)
    if "FOR PARTS" in text or "NOT WORKING" in text or "PARTS ONLY" in text:
        return True, "Title/description suggests parts/not working"
    return False, ""


def _filter_non_us_seller(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard if the seller is outside the United States.

    The eBay filter already restricts itemLocationCountry:US, but seller
    location can differ. We check the location string as a heuristic.
    """
    location = item.get("location", "").upper()
    # If country code is embedded and it's not US, discard
    non_us_pattern = re.search(r'\(([A-Z]{2})\)', location)
    if non_us_pattern:
        code = non_us_pattern.group(1)
        if code != "US":
            return True, f"Seller/item outside US ({code})"
    return False, ""


def _filter_seller_feedback(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard if seller feedback is below 95% or fewer than 10 transactions."""
    pct = item.get("seller_feedback_pct")
    score = item.get("seller_feedback_score")

    if pct is not None and pct < FEEDBACK_MIN_PCT:
        return True, f"Seller feedback {pct:.1f}% < {FEEDBACK_MIN_PCT}% minimum"

    if score is not None and score < FEEDBACK_MIN_SCORE:
        return True, f"Seller feedback score {score} < {FEEDBACK_MIN_SCORE} minimum"

    return False, ""


def _filter_ending_auction(item: dict[str, Any]) -> tuple[bool, str]:
    """
    Discard pure auctions with fewer than 12 hours remaining
    unless Buy It Now is also available.
    """
    buying_options = [o.upper() for o in item.get("buying_options", [])]
    is_auction = "AUCTION" in buying_options
    has_bin = "FIXED_PRICE" in buying_options or "BUY_IT_NOW" in buying_options

    if not is_auction:
        return False, ""
    if has_bin:
        return False, ""  # Buy It Now available — keep it

    end_time_str = item.get("time_left", "")
    if not end_time_str:
        return False, ""  # Unknown end time — don't discard speculatively

    try:
        # eBay uses ISO 8601 timestamps
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        hours_left = (end_time - now).total_seconds() / 3600
        if hours_left < AUCTION_MIN_HOURS:
            return True, f"Auction ending in {hours_left:.1f}h (< {AUCTION_MIN_HOURS}h, no BIN)"
    except ValueError:
        pass  # Can't parse — don't discard

    return False, ""


def _filter_price_ceiling(item: dict[str, Any], max_price: float = 2000.0) -> tuple[bool, str]:
    """Discard if price exceeds the configured ceiling."""
    price = item.get("price", 0.0)
    if price <= 0:
        return False, ""  # No price data — don't discard
    if price > max_price:
        return True, f"Price ${price:.2f} exceeds ceiling ${max_price:.2f}"
    return False, ""


def _filter_5995wx_unless_anomaly(item: dict[str, Any]) -> tuple[bool, str]:
    """
    Discard 5995WX listings unless the price is a genuine anomaly (< $1,200).
    The 5995WX commands a heavy premium; we can't afford to pay for 64 cores.
    """
    text = _text_upper(item)
    if "5995WX" not in text:
        return False, ""
    price = item.get("price", 0.0)
    if price > 0 and price < CPU_5995WX_PRICE_THRESHOLD:
        return False, ""  # Price anomaly — keep and flag for manual review
    return True, f"5995WX at ${price:.2f} (not a price anomaly — too expensive)"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_filters(
    item: dict[str, Any],
    max_price: float = 2000.0,
    verbose: bool = False,
) -> tuple[bool, str]:
    """
    Apply all discard filters to a single item.

    Args:
        item: Normalized item dict from search.py.
        max_price: Configurable price ceiling.
        verbose: If True, print the discard reason to stdout.

    Returns:
        (discard: bool, reason: str)
        discard=True means the item should be dropped from results.
    """
    checks = [
        _filter_3000_series,
        _filter_parts_condition,
        _filter_non_us_seller,
        _filter_seller_feedback,
        _filter_ending_auction,
        lambda i: _filter_price_ceiling(i, max_price),
        _filter_5995wx_unless_anomaly,
    ]

    for check in checks:
        discard, reason = check(item)
        if discard:
            if verbose:
                title = item.get("title", "?")[:60]
                print(f"  [DISCARD] {title!r}: {reason}")
            return True, reason

    return False, ""


def filter_items(
    items: list[dict[str, Any]],
    max_price: float = 2000.0,
    verbose: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Apply filters to a list of items.

    Returns:
        (kept, discarded) lists of item dicts.
        Discarded items have a 'discard_reason' field added.
    """
    kept = []
    discarded = []
    for item in items:
        discard, reason = apply_filters(item, max_price=max_price, verbose=verbose)
        if discard:
            item = dict(item)
            item["discard_reason"] = reason
            discarded.append(item)
        else:
            kept.append(item)
    return kept, discarded

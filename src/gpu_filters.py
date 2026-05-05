"""
Automatic discard filter logic — RTX 3090 GPU hunter.

Stricter thresholds than workstation filters: GPU fraud profile is higher.
Each predicate returns (discard: bool, reason: str).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEEDBACK_MIN_PCT = 98.0       # Stricter than workstation (95%)
FEEDBACK_MIN_SCORE = 50       # Stricter than workstation (10)
AUCTION_MIN_HOURS = 24        # Stricter than workstation (12h) — GPU auctions attract shill bids

GPU_PRICE_FLOOR = 350.0
GPU_PRICE_CEILING = 1000.0

PARTS_CONDITIONS = {
    "FOR_PARTS_OR_NOT_WORKING",
    "FOR PARTS OR NOT WORKING",
    "FOR_PARTS",
    "PARTS ONLY",
}

# Wrong card models — 40-series and non-3090 30-series
WRONG_CARD_PATTERNS = [
    r"\bRTX\s*3090\s*Ti\b",
    r"\bRTX\s*3080\b",
    r"\bRTX\s*3070\b",
    r"\bRTX\s*3060\b",
    r"\bRTX\s*40[0-9]{2}\b",
    r"\bRTX\s*4090\b",
    r"\bRTX\s*4080\b",
]

# VRAM sizes that indicate wrong card
WRONG_VRAM_PATTERNS = [
    r"\b10\s*GB\b",
    r"\b12\s*GB\b",
    r"\b16\s*GB\b",
]

# CMP (Crypto Mining Processor) — no display output, not usable
CMP_PATTERNS = [r"\bCMP\b", r"crypto\s+mining\s+processor"]


def _text(item: dict[str, Any]) -> str:
    return item.get("title", "") + " " + item.get("short_description", "")


def _text_upper(item: dict[str, Any]) -> str:
    return _text(item).upper()


# ---------------------------------------------------------------------------
# Individual filter predicates
# ---------------------------------------------------------------------------

def _filter_wrong_card(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard Ti variant, 3080/3070, and 40-series mentions."""
    text = _text(item)
    for pat in WRONG_CARD_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True, f"Wrong card model detected: {pat}"
    return False, ""


def _filter_wrong_vram(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard listings that explicitly state 10/12/16GB VRAM (not 3090)."""
    text = _text(item)
    # Only flag if these appear without "24GB" also being present
    has_24gb = bool(re.search(r"\b24\s*GB\b", text, re.IGNORECASE))
    if has_24gb:
        return False, ""
    for pat in WRONG_VRAM_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True, f"Wrong VRAM size detected ({pat}) without 24GB confirmation"
    return False, ""


def _filter_cmp(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard CMP (Crypto Mining Processor) variants — no display output."""
    text = _text(item)
    for pat in CMP_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True, "CMP variant detected — no display output"
    return False, ""


def _filter_parts_condition(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard 'for parts / not working' condition listings."""
    condition = item.get("condition", "").upper().replace("-", "_").replace(" ", "_")
    if condition in {c.upper().replace(" ", "_") for c in PARTS_CONDITIONS}:
        return True, f"Condition is 'for parts/not working' ({item.get('condition')})"
    text = _text_upper(item)
    if "FOR PARTS" in text or "NOT WORKING" in text or "PARTS ONLY" in text:
        return True, "Title/description suggests parts/not working"
    return False, ""


def _filter_non_us_seller(item: dict[str, Any]) -> tuple[bool, str]:
    location = item.get("location", "").upper()
    non_us = re.search(r'\(([A-Z]{2})\)', location)
    if non_us:
        code = non_us.group(1)
        if code != "US":
            return True, f"Seller/item outside US ({code})"
    return False, ""


def _filter_seller_feedback(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard if feedback < 98% or fewer than 50 transactions (feedbackScore proxy)."""
    pct = item.get("seller_feedback_pct")
    score = item.get("seller_feedback_score")

    if pct is not None and pct < FEEDBACK_MIN_PCT:
        return True, f"Seller feedback {pct:.1f}% < {FEEDBACK_MIN_PCT}% GPU minimum"

    if score is not None and score < FEEDBACK_MIN_SCORE:
        return True, f"Seller feedback score {score} < {FEEDBACK_MIN_SCORE} GPU minimum"

    return False, ""


def _filter_ending_auction(item: dict[str, Any]) -> tuple[bool, str]:
    """Discard pure auctions with <24h remaining and no Buy It Now."""
    buying_options = [o.upper() for o in item.get("buying_options", [])]
    is_auction = "AUCTION" in buying_options
    has_bin = "FIXED_PRICE" in buying_options or "BUY_IT_NOW" in buying_options

    if not is_auction or has_bin:
        return False, ""

    end_time_str = item.get("time_left", "")
    if not end_time_str:
        return False, ""

    try:
        end_time = datetime.fromisoformat(end_time_str.replace("Z", "+00:00"))
        hours_left = (end_time - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < AUCTION_MIN_HOURS:
            return True, f"GPU auction ending in {hours_left:.1f}h (< {AUCTION_MIN_HOURS}h, no BIN)"
    except ValueError:
        pass

    return False, ""


def _filter_price_ceiling(item: dict[str, Any], max_price: float = GPU_PRICE_CEILING) -> tuple[bool, str]:
    price = item.get("price", 0.0)
    if price > 0 and price > max_price:
        return True, f"Price ${price:.0f} exceeds GPU ceiling ${max_price:.0f}"
    return False, ""


def _filter_price_floor(item: dict[str, Any]) -> tuple[bool, str]:
    price = item.get("price", 0.0)
    if price > 0 and price < GPU_PRICE_FLOOR:
        return True, f"Price ${price:.0f} below GPU floor ${GPU_PRICE_FLOOR:.0f} (likely damaged/scam)"
    return False, ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_gpu_filters(
    item: dict[str, Any],
    max_price: float = GPU_PRICE_CEILING,
    verbose: bool = False,
) -> tuple[bool, str]:
    checks = [
        _filter_wrong_card,
        _filter_wrong_vram,
        _filter_cmp,
        _filter_parts_condition,
        _filter_non_us_seller,
        _filter_seller_feedback,
        _filter_ending_auction,
        lambda i: _filter_price_ceiling(i, max_price),
        _filter_price_floor,
    ]

    for check in checks:
        discard, reason = check(item)
        if discard:
            if verbose:
                title = item.get("title", "?")[:60]
                print(f"  [GPU DISCARD] {title!r}: {reason}")
            return True, reason

    return False, ""


def filter_gpu_items(
    items: list[dict[str, Any]],
    max_price: float = GPU_PRICE_CEILING,
    verbose: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept, discarded = [], []
    for item in items:
        discard, reason = apply_gpu_filters(item, max_price=max_price, verbose=verbose)
        if discard:
            item = dict(item)
            item["discard_reason"] = reason
            discarded.append(item)
        else:
            kept.append(item)
    return kept, discarded

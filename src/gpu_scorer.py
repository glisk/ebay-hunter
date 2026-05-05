"""
Scoring model for eBay RTX 3090 GPU listings.

Each listing receives a base score 0–100 with mining penalties applied after.
Listings below 40 are silently discarded.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GPU_SCORE_DISCARD_THRESHOLD = 40

TIER_PRIORITY = "PRIORITY"   # 70–100
TIER_REVIEW = "REVIEW"       # 55–69
TIER_MARGINAL = "MARGINAL"   # 40–54
TIER_DISCARD = "DISCARD"     # <40

# Flag names
FLAG_SUSPICIOUS_LOW = "SUSPICIOUS_LOW"
FLAG_MINING_DISCLOSED = "MINING_DISCLOSED"
FLAG_BIOS_MODIFIED = "BIOS_MODIFIED"
FLAG_REPASTED = "REPASTED"
FLAG_NVLINK_INCLUDED = "NVLINK_INCLUDED"
FLAG_TITLE_INCONSISTENCY = "TITLE_INCONSISTENCY"
FLAG_NO_ACTUAL_PHOTO = "NO_ACTUAL_PHOTO"
FLAG_NEW = "NEW"
FLAG_PRICE_DROP = "PRICE_DROP"

# ---------------------------------------------------------------------------
# Pricing model
# ---------------------------------------------------------------------------
# (condition_key): (low, high, suspicious_below, overpriced_above)
# condition_key: "refurbished" | "nvlink" | "standard"
GPU_PRICE_TABLE = {
    "refurbished": (700,  950,  600,  1000),
    "nvlink":      (650,  875,  550,  1000),
    "standard":    (600,  800,  500,   900),
}


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------

def _text(item: dict[str, Any]) -> str:
    return item.get("title", "") + " " + item.get("short_description", "")


def detect_card_confirmed(item: dict[str, Any]) -> str:
    """
    Return 'confirmed', 'ambiguous', or 'wrong' based on title analysis.

    confirmed  — title has '3090' (not Ti) and '24GB'
    ambiguous  — title has '3090' (not Ti) but no explicit 24GB
    wrong      — Ti, wrong model, or no 3090 mention at all
    """
    text = _text(item)
    title = item.get("title", "")

    # Ti variant is a wrong card (should have been discarded, but be defensive)
    if re.search(r"\bRTX\s*3090\s*Ti\b", text, re.IGNORECASE):
        return "wrong"

    has_3090 = bool(re.search(r"\b3090\b", title, re.IGNORECASE))
    has_24gb = bool(re.search(r"\b24\s*GB\b", text, re.IGNORECASE))

    if not has_3090:
        return "wrong"
    if has_24gb:
        return "confirmed"
    return "ambiguous"


def detect_mining_flags(item: dict[str, Any]) -> list[str]:
    """Return list of mining-related flags detected in listing text."""
    text = _text(item).lower()
    flags: list[str] = []

    bios_patterns = [
        r"bios\s+modified", r"mining\s+bios", r"custom\s+bios", r"modded\s+bios",
    ]
    mining_patterns = [
        r"\bmining\b", r"\bmined\b", r"\bcrypto\b", r"\bethereum\b", r"\beth\b",
        r"used\s+for\s+compute", r"\b24/7\b", r"datacenter\s+use",
        r"fans?\s+replaced", r"fan\s+replacement",
    ]
    repaste_patterns = [
        r"thermal\s+paste\s+replaced", r"\brepasted\b", r"re-pasted",
        r"new\s+thermal\s+paste", r"fresh\s+thermal",
    ]

    has_bios = any(re.search(p, text) for p in bios_patterns)
    has_mining = any(re.search(p, text) for p in mining_patterns)
    has_repaste = any(re.search(p, text) for p in repaste_patterns)

    if has_bios:
        flags.append(FLAG_BIOS_MODIFIED)
        if FLAG_MINING_DISCLOSED not in flags:
            flags.append(FLAG_MINING_DISCLOSED)
    if has_mining and FLAG_MINING_DISCLOSED not in flags:
        flags.append(FLAG_MINING_DISCLOSED)
    if has_repaste:
        flags.append(FLAG_REPASTED)

    return flags


def detect_nvlink(item: dict[str, Any]) -> bool:
    """Return True if an NVLink bridge is mentioned in the listing."""
    text = _text(item)
    return bool(re.search(r"\bnvlink\b|\bnv\s+link\b", text, re.IGNORECASE))


def detect_condition_tier(item: dict[str, Any]) -> tuple[str, int]:
    """
    Detect condition quality tier from eBay condition field and listing text.

    Returns (tier_label, points) where points is 0–15.

    Tiers (highest match wins):
      'tested_photos'   — 15: tested + working + actual photo clues
      'tested'          — 10: tested + working, no photo confirmation
      'refurbished'     —  8: eBay condition = SELLER_REFURBISHED
      'used'            —  5: Used with no meaningful condition statement
      'as_is'           —  0: as-is / untested / sold as-is
    """
    text = _text(item).lower()
    condition_field = item.get("condition", "").upper()

    # As-is / untested — lowest tier
    if re.search(r"\bas[\s-]+is\b|\buntested\b|\bsold\s+as[\s-]+is\b", text):
        return "as_is", 0

    tested = bool(re.search(
        r"tested\s+and\s+working|tested[\s,]+working|tested\s*&\s*working"
        r"|works\s+perfectly|fully\s+functional|100%\s+working",
        text,
    ))

    actual_photo = bool(re.search(
        r"actual\s+photo|actual\s+image|photos?\s+of\s+(the\s+)?actual"
        r"|real\s+photos?|photos?\s+taken\s+by\s+(me|seller)"
        r"|my\s+(own\s+)?photos?|these\s+are\s+my\s+photos?",
        text,
    ))

    if tested and actual_photo:
        return "tested_photos", 15
    if tested:
        return "tested", 10
    if "SELLER_REFURBISHED" in condition_field or "SELLER_REFURBISH" in condition_field:
        return "refurbished", 8
    return "used", 5


def detect_return_policy_pts(return_policy: str) -> int:
    """Score return policy string. 5 for 30-day, 3 for 14-day, 0 otherwise."""
    if "30" in return_policy and "return" in return_policy.lower():
        return 5
    if "14" in return_policy and "return" in return_policy.lower():
        return 3
    return 0


def detect_title_inconsistency(item: dict[str, Any]) -> bool:
    """Flag if title says RTX 3090 but also mentions a different GPU model number."""
    text = _text(item)
    has_3090 = bool(re.search(r"\b3090\b", text, re.IGNORECASE))
    has_other = bool(re.search(r"\b(3080|3070|3060|4090|4080|4070|2080|2070)\b", text, re.IGNORECASE))
    return has_3090 and has_other


def detect_no_actual_photo(item: dict[str, Any]) -> bool:
    """Flag stock photo / placeholder image language."""
    text = _text(item).lower()
    return bool(re.search(
        r"image\s+for\s+illustration|stock\s+photo|actual\s+item\s+may\s+differ"
        r"|for\s+illustration\s+only|representative\s+image",
        text,
    ))


# ---------------------------------------------------------------------------
# Pricing score
# ---------------------------------------------------------------------------

def _price_row(condition_key: str, nvlink: bool) -> tuple[float, float, float, float]:
    if nvlink and condition_key != "refurbished":
        return GPU_PRICE_TABLE["nvlink"]
    return GPU_PRICE_TABLE.get(condition_key, GPU_PRICE_TABLE["standard"])


def score_gpu_price(
    price: float,
    condition_key: str,
    nvlink: bool,
) -> tuple[int, list[str]]:
    """Return (price_score 0–20, price_flags)."""
    if price <= 0:
        return 10, []

    low, high, suspicious, overpriced = _price_row(condition_key, nvlink)
    flags: list[str] = []

    if price < suspicious:
        flags.append(FLAG_SUSPICIOUS_LOW)
        return 10, flags

    if price <= low * 0.85 or low <= price <= high:
        return 20, flags

    if price <= high * 1.15:
        return 10, flags

    return 0, flags


# ---------------------------------------------------------------------------
# Seller qualification score
# ---------------------------------------------------------------------------

def score_gpu_seller(feedback_pct: float | None, feedback_score: int | None) -> int:
    """Return seller qualification score 0–20."""
    if feedback_pct is None:
        return 0
    score = feedback_score or 0

    if feedback_pct >= 99.5 and score >= 100:
        return 20
    if feedback_pct >= 99.0 and score >= 50:
        return 15
    if feedback_pct >= 98.0 and score >= 50:
        return 10
    return 0


# ---------------------------------------------------------------------------
# Card confirmation score
# ---------------------------------------------------------------------------

def score_card_confirmed(confirmed: str) -> int:
    """Return card confirmation score 0–30."""
    return {"confirmed": 30, "ambiguous": 15, "wrong": 0}.get(confirmed, 0)


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_gpu_listing(item: dict[str, Any]) -> dict[str, Any]:
    """
    Score a single normalized GPU item dict.

    Returns an enriched copy with scoring fields added:
      - card_confirmed
      - condition_tier
      - nvlink_included
      - score, score_breakdown, tier, flags
    """
    item = dict(item)

    price = item.get("price", 0.0)
    feedback_pct = item.get("seller_feedback_pct")
    feedback_score = item.get("seller_feedback_score")
    return_policy = item.get("return_policy", "No returns")
    local_pickup = item.get("local_pickup", False)

    flags: list[str] = list(item.get("flags", []))

    # Detections
    card_status = detect_card_confirmed(item)
    mining_flags = detect_mining_flags(item)
    nvlink = detect_nvlink(item)
    condition_tier, condition_pts = detect_condition_tier(item)

    for f in mining_flags:
        if f not in flags:
            flags.append(f)

    if nvlink and FLAG_NVLINK_INCLUDED not in flags:
        flags.append(FLAG_NVLINK_INCLUDED)

    if detect_title_inconsistency(item):
        flags.append(FLAG_TITLE_INCONSISTENCY)

    if detect_no_actual_photo(item):
        flags.append(FLAG_NO_ACTUAL_PHOTO)

    # Determine price row condition key
    condition_key = "refurbished" if condition_tier == "refurbished" else "standard"

    breakdown: dict[str, int] = {}

    # Card confirmed (30)
    card_pts = score_card_confirmed(card_status)
    breakdown["card_confirmed"] = card_pts

    # Seller qualification (20)
    seller_pts = score_gpu_seller(feedback_pct, feedback_score)
    breakdown["seller_qualification"] = seller_pts

    # Price (20)
    price_pts, price_flags = score_gpu_price(price, condition_key, nvlink)
    for f in price_flags:
        if f not in flags:
            flags.append(f)
    breakdown["price"] = price_pts

    # Condition / disclosure (15)
    breakdown["condition"] = condition_pts

    # NVLink (5)
    nvlink_pts = 5 if nvlink else 0
    breakdown["nvlink"] = nvlink_pts

    # Return policy (5)
    return_pts = detect_return_policy_pts(return_policy)
    breakdown["return_policy"] = return_pts

    # Local pickup (5)
    pickup_pts = 5 if local_pickup else 0
    breakdown["local_pickup"] = pickup_pts

    base_score = sum(breakdown.values())

    # Mining penalties (applied after base, independent per flag)
    mining_penalty = 0
    if FLAG_MINING_DISCLOSED in flags:
        mining_penalty += 5
    if FLAG_BIOS_MODIFIED in flags:
        mining_penalty += 10
    breakdown["mining_penalty"] = -mining_penalty

    total = max(0, min(100, base_score - mining_penalty))

    if total >= 70:
        tier = TIER_PRIORITY
    elif total >= 55:
        tier = TIER_REVIEW
    elif total >= GPU_SCORE_DISCARD_THRESHOLD:
        tier = TIER_MARGINAL
    else:
        tier = TIER_DISCARD

    item["card_confirmed"] = card_status
    item["condition_tier"] = condition_tier
    item["nvlink_included"] = nvlink
    item["score"] = total
    item["score_breakdown"] = breakdown
    item["tier"] = tier
    item["flags"] = flags

    return item


def score_gpu_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Score a list of GPU items, discard below threshold, sort by score descending."""
    scored = [score_gpu_listing(item) for item in items]
    kept = [i for i in scored if i["score"] >= GPU_SCORE_DISCARD_THRESHOLD]
    kept.sort(key=lambda x: x["score"], reverse=True)
    return kept

"""
Scoring model and pricing model for eBay workstation listings.

Each listing receives a score 0–100. Scores below 40 are silently discarded.
Scores are deterministic given the same listing data.
"""

from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCORE_DISCARD_THRESHOLD = 40

TIER_PRIORITY = "PRIORITY"   # 70–100
TIER_REVIEW = "REVIEW"       # 55–69
TIER_MARGINAL = "MARGINAL"   # 40–54
TIER_DISCARD = "DISCARD"     # <40

# CPU detection
CPU_5000 = ["5945WX", "5955WX", "5965WX", "5975WX", "5995WX"]
CPU_3000 = ["3945WX", "3955WX", "3975WX", "3995WX"]

# PSU wattage keywords
PSU_GREEN_PATTERNS = [r"\b900W\b", r"\b1000W\b", r"\b1200W\b", r"\b1[Kk]W\b", r"\b1\.0?[Kk]W\b"]
PSU_RED_PATTERNS = [r"\b450W\b"]

# RAM detection — order matters, more specific first
RAM_PATTERNS = [
    (r"\b512\s*GB\b", 512),
    (r"\b256\s*GB\b", 256),
    (r"\b192\s*GB\b", 192),
    (r"\b128\s*GB\b", 128),
    (r"\b64\s*GB\b", 64),
    (r"\b32\s*GB\b", 32),
    (r"\b16\s*GB\b", 16),
]

# GPU detection (present = paying for something not wanted)
GPU_PATTERNS = [
    r"\bRTX\s*\d+",
    r"\bGTX\s*\d+",
    r"\bQuadro\b",
    r"\bRadeon\s*(RX|Pro)\b",
    r"\bGeForce\b",
    r"\bA\d000\b",   # A4000, A5000, A6000 Quadro series
    r"\bV100\b",
    r"\bA100\b",
]

# Storage detection
STORAGE_PATTERNS = [r"\bNVMe\b", r"\bSSD\b", r"\bM\.2\b", r"\bTB\b", r"\bGB\s*SSD\b"]

# ---------------------------------------------------------------------------
# Pricing model
# ---------------------------------------------------------------------------

# (cpu, min_ram_gb): (low_expected, high_expected, suspicious_low, overpriced_above)
PRICE_TABLE: dict[tuple[str, int], tuple[float, float, float, float]] = {
    ("5945WX", 64):  (700,  1000, 500,  1100),
    ("5945WX", 128): (1000, 1400, 700,  1600),
    ("5955WX", 128): (1100, 1500, 800,  1700),
    ("5965WX", 128): (1200, 1800, 900,  2000),
    ("5975WX", 128): (1400, 2000, 1100, 2200),
}
PRICE_UNKNOWN = (800, 1600, 600, 2000)

FLAG_SUSPICIOUS_LOW = "SUSPICIOUS_LOW"
FLAG_NEW = "NEW"
FLAG_PRICE_DROP = "PRICE_DROP"
FLAG_5995WX_ANOMALY = "5995WX_ANOMALY"

PSU_GREEN = "GREEN"
PSU_YELLOW = "YELLOW"
PSU_RED = "RED"


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _text(item: dict[str, Any]) -> str:
    """Combined title + short description for pattern matching."""
    return item.get("title", "") + " " + item.get("short_description", "")


def detect_cpu(item: dict[str, Any]) -> str | None:
    """Return the CPU model string if detected, else None."""
    text = _text(item).upper()
    for cpu in CPU_5000:
        if cpu in text:
            return cpu
    for cpu in CPU_3000:
        if cpu in text:
            return cpu
    return None


def detect_ram(item: dict[str, Any]) -> int | None:
    """Return detected RAM in GB, or None if not found."""
    text = _text(item)
    for pattern, gb in RAM_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return gb
    return None


def detect_psu(item: dict[str, Any]) -> str:
    """Return PSU classification: GREEN, YELLOW, or RED."""
    text = _text(item)
    for pat in PSU_GREEN_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return PSU_GREEN
    for pat in PSU_RED_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return PSU_RED
    return PSU_YELLOW


def detect_gpu(item: dict[str, Any]) -> bool | None:
    """
    Return True if a discrete GPU is mentioned, False if explicitly no GPU,
    None if unspecified.
    """
    text = _text(item)
    for pat in GPU_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    # Explicit "no GPU" indicators
    if re.search(r"\bno\s+gpu\b|\bno\s+graphics\b|\bwithout\s+gpu\b", text, re.IGNORECASE):
        return False
    return None


def detect_storage(item: dict[str, Any]) -> bool:
    """Return True if any SSD/NVMe storage is mentioned."""
    text = _text(item)
    for pat in STORAGE_PATTERNS:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


# ---------------------------------------------------------------------------
# Pricing score
# ---------------------------------------------------------------------------

def _price_row(cpu: str | None, ram_gb: int | None) -> tuple[float, float, float, float]:
    """Look up the price expectations for a given CPU + RAM config."""
    if cpu in CPU_3000:
        return PRICE_UNKNOWN  # Shouldn't reach here after filters, but safe fallback

    if cpu is None or ram_gb is None:
        return PRICE_UNKNOWN

    # Find the best matching row
    if cpu == "5945WX":
        key = ("5945WX", 64 if ram_gb < 128 else 128)
    elif cpu in CPU_5000:
        key = (cpu, 128)
    else:
        return PRICE_UNKNOWN

    return PRICE_TABLE.get(key, PRICE_UNKNOWN)


def score_price(price: float, cpu: str | None, ram_gb: int | None) -> tuple[int, list[str]]:
    """
    Compute price score (0–10) and any price-related flags.

    Returns:
        (score, flags)
    """
    if price <= 0:
        return 5, []  # Unknown price — neutral score

    low, high, suspicious, overpriced = _price_row(cpu, ram_gb)
    flags: list[str] = []

    if price <= suspicious:
        flags.append(FLAG_SUSPICIOUS_LOW)
        # Check 5995WX anomaly separately
        if cpu == "5995WX":
            flags.append(FLAG_5995WX_ANOMALY)
        return 5, flags

    if price <= low * 0.85:
        # Up to 15% below low — potential deal, full points
        return 10, flags

    if low <= price <= high:
        return 10, flags

    if price <= high * 1.15:
        # Up to 15% above high end
        return 5, flags

    # Overpriced
    return 0, flags


# ---------------------------------------------------------------------------
# Main scoring function
# ---------------------------------------------------------------------------

def score_listing(item: dict[str, Any]) -> dict[str, Any]:
    """
    Score a single normalized item dict.

    Returns an enriched copy of the item with scoring fields added:
      - cpu_detected
      - ram_detected
      - psu_status
      - gpu_detected
      - storage_detected
      - score
      - score_breakdown (dict of criterion -> points)
      - tier
      - flags
    """
    item = dict(item)  # Don't mutate the original

    cpu = detect_cpu(item)
    ram_gb = detect_ram(item)
    psu = detect_psu(item)
    gpu = detect_gpu(item)
    storage = detect_storage(item)
    price = item.get("price", 0.0)

    item["cpu_detected"] = cpu
    item["ram_detected"] = f"{ram_gb}GB" if ram_gb else None
    item["psu_status"] = psu

    flags: list[str] = list(item.get("flags", []))
    breakdown: dict[str, int] = {}

    # --- CPU generation (25 pts) ---
    if cpu in CPU_5000:
        cpu_pts = 25
    elif cpu in CPU_3000:
        cpu_pts = 0  # Should have been filtered, but handle defensively
    else:
        cpu_pts = 10  # Unknown/unspecified — partial
    breakdown["cpu_generation"] = cpu_pts

    # --- RAM (20 pts) ---
    if ram_gb is None:
        ram_pts = 0
    elif ram_gb >= 128:
        ram_pts = 20
    elif ram_gb >= 64:
        ram_pts = 10
    else:
        ram_pts = 0
    breakdown["ram"] = ram_pts

    # --- PSU (20 pts) ---
    if psu == PSU_GREEN:
        psu_pts = 20
    elif psu == PSU_YELLOW:
        psu_pts = 10
    else:  # RED
        psu_pts = 0
    breakdown["psu"] = psu_pts

    # --- Seller feedback (10 pts) ---
    feedback_pct = item.get("seller_feedback_pct")
    if feedback_pct is None:
        feedback_pts = 5  # Unknown — neutral
    elif feedback_pct >= 99.0:
        feedback_pts = 10
    elif feedback_pct >= 98.0:
        feedback_pts = 8
    elif feedback_pct >= 97.0:
        feedback_pts = 6
    elif feedback_pct >= 95.0:
        feedback_pts = 4
    else:
        feedback_pts = 0
    breakdown["seller_feedback"] = feedback_pts

    # --- Price vs expected range (10 pts) ---
    price_pts, price_flags = score_price(price, cpu, ram_gb)
    flags.extend(price_flags)
    breakdown["price"] = price_pts

    # --- No GPU included (5 pts) ---
    if gpu is False:
        gpu_pts = 5  # Explicitly no GPU
    elif gpu is None:
        gpu_pts = 3  # Unspecified
    else:
        gpu_pts = 2  # GPU included (paying for something not needed)
    breakdown["no_gpu"] = gpu_pts

    # --- Local pickup (5 pts) ---
    local_pts = 5 if item.get("local_pickup") else 0
    breakdown["local_pickup"] = local_pts

    # --- Storage (5 pts) ---
    storage_pts = 5 if storage else 0
    breakdown["storage"] = storage_pts

    total = sum(breakdown.values())
    total = min(100, max(0, total))

    # Assign tier
    if total >= 70:
        tier = TIER_PRIORITY
    elif total >= 55:
        tier = TIER_REVIEW
    elif total >= SCORE_DISCARD_THRESHOLD:
        tier = TIER_MARGINAL
    else:
        tier = TIER_DISCARD

    item["score"] = total
    item["score_breakdown"] = breakdown
    item["tier"] = tier
    item["flags"] = flags
    item["gpu_detected"] = gpu
    item["storage_detected"] = storage

    return item


# Keep score_item as an alias for backward compatibility
score_item = score_listing


def score_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Score a list of items, discard those below threshold, sort by score descending.

    Returns only items with score >= SCORE_DISCARD_THRESHOLD.
    """
    scored = [score_listing(item) for item in items]
    kept = [i for i in scored if i["score"] >= SCORE_DISCARD_THRESHOLD]
    kept.sort(key=lambda x: x["score"], reverse=True)
    return kept


def tier_label(tier: str) -> str:
    """Human-readable tier label."""
    return {
        TIER_PRIORITY: "PRIORITY",
        TIER_REVIEW: "REVIEW",
        TIER_MARGINAL: "MARGINAL",
        TIER_DISCARD: "DISCARD",
    }.get(tier, tier)

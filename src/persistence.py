"""
Persistence layer: results.json, high-priority.json, run-log.json.

Handles:
- Loading and saving the full results store
- Change detection (new / price drop / disappeared)
- Writing high-priority subset
- Appending to the run log
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).parent.parent / "cache"
RESULTS_PATH = CACHE_DIR / "results.json"
HIGH_PRIORITY_PATH = CACHE_DIR / "high-priority.json"
RUN_LOG_PATH = CACHE_DIR / "run-log.json"

# Tier constant — keep in sync with scorer.py to avoid circular import
TIER_PRIORITY = "PRIORITY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Load / Save results store
# ---------------------------------------------------------------------------

def load_cache() -> dict[str, dict[str, Any]]:
    """
    Load the full results store from cache/results.json.

    Returns a dict keyed by item_id. Returns empty dict if file doesn't exist.
    """
    if not RESULTS_PATH.exists():
        return {}
    try:
        with RESULTS_PATH.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# Keep load_results as an alias for backward compatibility
load_results = load_cache


def save_results(store: dict[str, dict[str, Any]]) -> None:
    """Write the full results store to cache/results.json."""
    _ensure_cache_dir()
    with RESULTS_PATH.open("w") as f:
        json.dump(store, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Change detection and store update
# ---------------------------------------------------------------------------

def merge_run(
    scored_items: list[dict[str, Any]],
    store: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],  # updated store
    list[dict[str, Any]],       # new listings
    list[dict[str, Any]],       # price drops (with old_price field)
    list[dict[str, Any]],       # disappeared listings
]:
    """
    Reconcile a fresh set of scored items against the existing cache.

    Returns:
        updated_store: The new state of the full cache (ready to save).
        new_listings: Items not seen in a previous run.
        price_drops: Items whose price decreased since last seen.
        disappeared: Items in the cache not present in the current run,
                     now marked as sold_or_pulled.
    """
    now = _now_iso()
    current_ids = {item["item_id"] for item in scored_items if item.get("item_id")}

    new_listings: list[dict[str, Any]] = []
    price_drops: list[dict[str, Any]] = []
    disappeared: list[dict[str, Any]] = []

    # Process current run items
    updated_store = dict(store)

    for item in scored_items:
        iid = item.get("item_id")
        if not iid:
            continue

        flags = list(item.get("flags", []))

        if iid not in store:
            # New listing
            flags.append("NEW")
            record = _make_record(item, flags, now, now, status="active")
            new_listings.append(record)
        else:
            prev = store[iid]
            prev_price = prev.get("price", 0.0)
            curr_price = item.get("price", 0.0)

            # Price drop detection
            if prev_price > 0 and curr_price > 0 and curr_price < prev_price:
                flags.append("PRICE_DROP")
                record = _make_record(item, flags, prev.get("first_seen", now), now, status="active")
                record["old_price"] = prev_price
                price_drops.append(record)
            else:
                record = _make_record(item, flags, prev.get("first_seen", now), now, status="active")

        updated_store[iid] = record

    # Mark disappeared items
    for iid, prev in store.items():
        if iid not in current_ids and prev.get("status") == "active":
            prev_copy = dict(prev)
            prev_copy["status"] = "sold_or_pulled"
            prev_copy["last_seen"] = now
            updated_store[iid] = prev_copy
            disappeared.append(prev_copy)

    return updated_store, new_listings, price_drops, disappeared


def _make_record(
    item: dict[str, Any],
    flags: list[str],
    first_seen: str,
    last_seen: str,
    status: str = "active",
) -> dict[str, Any]:
    """Build a cache record from a scored item dict."""
    return {
        "item_id": item.get("item_id", ""),
        "title": item.get("title", ""),
        "price": item.get("price", 0.0),
        "score": item.get("score", 0),
        "tier": item.get("tier", ""),
        "psu_status": item.get("psu_status", "YELLOW"),
        "psu_source": item.get("psu_source", "unknown"),
        "cpu_detected": item.get("cpu_detected"),
        "ram_detected": item.get("ram_detected"),
        "seller_feedback": item.get("seller_feedback_pct"),
        "url": item.get("url", ""),
        "location": item.get("location", ""),
        "local_pickup": item.get("local_pickup", False),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "status": status,
        "flags": list(set(flags)),  # deduplicate flags
        "score_breakdown": item.get("score_breakdown", {}),
        "variant_data": item.get("variant_data"),
    }


# ---------------------------------------------------------------------------
# High-priority file
# ---------------------------------------------------------------------------

def save_high_priority(store: dict[str, dict[str, Any]]) -> int:
    """
    Write all active PRIORITY-tier items to cache/high-priority.json.

    Returns the count of items written.
    """
    _ensure_cache_dir()
    priority = [
        rec for rec in store.values()
        if rec.get("status") == "active" and rec.get("tier") == TIER_PRIORITY
    ]
    priority.sort(key=lambda x: x.get("score", 0), reverse=True)
    with HIGH_PRIORITY_PATH.open("w") as f:
        json.dump(priority, f, indent=2, default=str)
    return len(priority)


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------

def append_run_log(
    total_fetched: int,
    after_dedup: int,
    after_discard: int,
    after_score: int,
    new_count: int,
    price_drop_count: int,
    disappeared_count: int,
    queries_run: list[str],
) -> None:
    """Append an entry to cache/run-log.json."""
    _ensure_cache_dir()

    entry = {
        "timestamp": _now_iso(),
        "queries_run": len(queries_run),
        "total_fetched": total_fetched,
        "after_dedup": after_dedup,
        "after_discard": after_discard,
        "after_score_threshold": after_score,
        "new_listings": new_count,
        "price_drops": price_drop_count,
        "disappeared": disappeared_count,
    }

    log: list[dict[str, Any]] = []
    if RUN_LOG_PATH.exists():
        try:
            with RUN_LOG_PATH.open() as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []

    log.append(entry)

    with RUN_LOG_PATH.open("w") as f:
        json.dump(log, f, indent=2, default=str)

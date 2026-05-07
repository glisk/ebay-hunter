"""
Persistence layer for GPU hunter: gpu_results.json, gpu-high-priority.json, gpu-run-log.json.

Separate from workstation persistence — cache files must not cross-pollute.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).parent.parent / "cache"
GPU_RESULTS_PATH = CACHE_DIR / "gpu_results.json"
GPU_HIGH_PRIORITY_PATH = CACHE_DIR / "gpu-high-priority.json"
GPU_RUN_LOG_PATH = CACHE_DIR / "gpu-run-log.json"

TIER_PRIORITY = "PRIORITY"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_cache_dir() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def load_gpu_cache() -> dict[str, dict[str, Any]]:
    """Load cache/gpu_results.json. Returns empty dict if absent."""
    if not GPU_RESULTS_PATH.exists():
        return {}
    try:
        with GPU_RESULTS_PATH.open() as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_gpu_results(store: dict[str, dict[str, Any]]) -> None:
    _ensure_cache_dir()
    with GPU_RESULTS_PATH.open("w") as f:
        json.dump(store, f, indent=2, default=str)


def merge_gpu_run(
    scored_items: list[dict[str, Any]],
    store: dict[str, dict[str, Any]],
) -> tuple[
    dict[str, dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    """
    Reconcile fresh GPU scored items against the cache.

    Returns (updated_store, new_listings, price_drops, disappeared).
    Also detects flag changes (e.g. mining flag newly added/removed).
    """
    now = _now_iso()
    current_ids = {item["item_id"] for item in scored_items if item.get("item_id")}

    new_listings: list[dict[str, Any]] = []
    price_drops: list[dict[str, Any]] = []
    disappeared: list[dict[str, Any]] = []

    updated_store = dict(store)

    for item in scored_items:
        iid = item.get("item_id")
        if not iid:
            continue

        flags = list(item.get("flags", []))

        if iid not in store:
            flags.append("NEW")
            record = _make_gpu_record(item, flags, now, now, status="active")
            new_listings.append(record)
        else:
            prev = store[iid]
            prev_price = prev.get("price", 0.0)
            curr_price = item.get("price", 0.0)

            # Flag change detection (mining flag newly appeared or removed)
            prev_flags = set(prev.get("flags", []))
            curr_flags = set(flags)
            mining_flags = {"MINING_DISCLOSED", "BIOS_MODIFIED"}
            if (mining_flags & curr_flags) != (mining_flags & prev_flags):
                flags.append("FLAG_CHANGED")

            if prev_price > 0 and curr_price > 0 and curr_price < prev_price:
                flags.append("PRICE_DROP")
                record = _make_gpu_record(item, flags, prev.get("first_seen", now), now, status="active")
                record["old_price"] = prev_price
                price_drops.append(record)
            else:
                record = _make_gpu_record(item, flags, prev.get("first_seen", now), now, status="active")

        updated_store[iid] = record

    for iid, prev in store.items():
        if iid not in current_ids and prev.get("status") == "active":
            prev_copy = dict(prev)
            prev_copy["status"] = "sold_or_pulled"
            prev_copy["last_seen"] = now
            updated_store[iid] = prev_copy
            disappeared.append(prev_copy)

    return updated_store, new_listings, price_drops, disappeared


def _make_gpu_record(
    item: dict[str, Any],
    flags: list[str],
    first_seen: str,
    last_seen: str,
    status: str = "active",
) -> dict[str, Any]:
    return {
        "item_id": item.get("item_id", ""),
        "title": item.get("title", ""),
        "price": item.get("price", 0.0),
        "score": item.get("score", 0),
        "tier": item.get("tier", ""),
        "card_confirmed": item.get("card_confirmed", "ambiguous"),
        "condition_tier": item.get("condition_tier", "used"),
        "nvlink_included": item.get("nvlink_included", False),
        "seller_feedback": item.get("seller_feedback_pct"),
        "seller_transactions": item.get("seller_feedback_score"),
        "return_policy": item.get("return_policy", "No returns"),
        "url": item.get("url", ""),
        "location": item.get("location", ""),
        "local_pickup": item.get("local_pickup", False),
        "description": item.get("description", ""),
        "first_seen": first_seen,
        "last_seen": last_seen,
        "status": status,
        "flags": list(set(flags)),
        "score_breakdown": item.get("score_breakdown", {}),
    }


def save_gpu_high_priority(store: dict[str, dict[str, Any]]) -> int:
    _ensure_cache_dir()
    priority = [
        rec for rec in store.values()
        if rec.get("status") == "active" and rec.get("tier") == TIER_PRIORITY
    ]
    priority.sort(key=lambda x: x.get("score", 0), reverse=True)
    with GPU_HIGH_PRIORITY_PATH.open("w") as f:
        json.dump(priority, f, indent=2, default=str)
    return len(priority)


def append_gpu_run_log(
    total_fetched: int,
    after_dedup: int,
    after_discard: int,
    after_score: int,
    new_count: int,
    price_drop_count: int,
    disappeared_count: int,
    queries_run: list[str],
) -> None:
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
    if GPU_RUN_LOG_PATH.exists():
        try:
            with GPU_RUN_LOG_PATH.open() as f:
                log = json.load(f)
        except (json.JSONDecodeError, OSError):
            log = []

    log.append(entry)

    with GPU_RUN_LOG_PATH.open("w") as f:
        json.dump(log, f, indent=2, default=str)

"""
Markdown report writer for cache/gpu-report.md.

Separate from workstation report — for independent hardware advisor review.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).parent.parent / "cache"
GPU_REPORT_PATH = CACHE_DIR / "gpu-report.md"

CONDITION_LABELS = {
    "tested_photos": "Tested + working (actual photos)",
    "tested":        "Tested + working",
    "refurbished":   "Seller refurbished",
    "used":          "Used",
    "as_is":         "As-is / untested",
}


def _fmt_price(price: float) -> str:
    return f"${price:,.0f}" if price > 0 else "?"


def _fmt_feedback(feedback: float | None) -> str:
    return f"{feedback:.1f}%" if feedback is not None else "unknown"


def _time_ago(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return f"{int(diff.total_seconds() / 60)}m ago"
        if hours < 48:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except ValueError:
        return ""


def _gpu_item_block(item: dict[str, Any], index: int) -> str:
    flags = item.get("flags", [])
    flag_str = f" `{'` `'.join(flags)}`" if flags else ""
    breakdown = item.get("score_breakdown", {})
    bd_str = "  ".join(f"{k}: {v}" for k, v in breakdown.items()) if breakdown else "n/a"
    feedback = item.get("seller_feedback") if item.get("seller_feedback") is not None else item.get("seller_feedback_pct")
    transactions = item.get("seller_transactions") if item.get("seller_transactions") is not None else item.get("seller_feedback_score")
    tx_str = f" ({transactions:,} transactions)" if transactions else ""
    condition = CONDITION_LABELS.get(item.get("condition_tier", ""), item.get("condition_tier", "unknown"))
    nvlink = item.get("nvlink_included", False)

    lines = [
        f"### {index}. {item.get('title', 'No title')[:100]}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Score | **{item.get('score', 0)}/100** ({item.get('tier', '')}){flag_str} |",
        f"| Price | {_fmt_price(item.get('price', 0))} |",
        f"| Card | {item.get('card_confirmed', 'ambiguous')} |",
        f"| Condition | {condition} |",
        f"| NVLink bridge | {'Yes ✓' if nvlink else 'Not mentioned'} |",
        f"| Return policy | {item.get('return_policy', 'No returns')} |",
        f"| Seller feedback | {_fmt_feedback(feedback)}{tx_str} |",
        f"| Local pickup | {'Yes' if item.get('local_pickup') else 'No'} |",
        f"| First seen | {_time_ago(item.get('first_seen', ''))} |",
        f"| URL | {item.get('url', '')} |",
        f"| Score breakdown | {bd_str} |",
    ]
    return "\n".join(lines)


def write_gpu_report(
    scored_items: list[dict[str, Any]],
    new_listings: list[dict[str, Any]],
    price_drops: list[dict[str, Any]],
    disappeared: list[dict[str, Any]],
    total_fetched: int,
    after_dedup: int,
    after_discard: int,
    history_depth: int = 0,
    obs_excluded: int = 0,
) -> Path:
    """Write cache/gpu-report.md and return its path."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    priority = [i for i in scored_items if i.get("tier") == "PRIORITY"]
    review   = [i for i in scored_items if i.get("tier") == "REVIEW"]
    marginal = [i for i in scored_items if i.get("tier") == "MARGINAL"]

    sections: list[str] = []

    sections.append(f"# eBay GPU Hunter Report — RTX 3090 — {now}\n")
    sections.append("> Market intelligence only — purchase decision pending workstation confirmation.\n")

    # Run summary
    sections.append("## Run Summary\n")
    day_word = "day" if history_depth == 1 else "days"
    depth_note = (
        f"{history_depth} {day_word}"
        if history_depth >= 90
        else f"{history_depth} {day_word} (90 days needed for full signal)"
    )
    excluded_note = f"| Observations excluded (SUSPICIOUS_LOW) | {obs_excluded} |\n" if obs_excluded else ""
    sections.append(
        f"| | |\n|---|---|\n"
        f"| Total fetched | {total_fetched} |\n"
        f"| After dedup | {after_dedup} |\n"
        f"| After discard filters | {after_discard} |\n"
        f"| Scored (above threshold) | {len(scored_items)} |\n"
        f"| New listings | {len(new_listings)} |\n"
        f"| Price drops | {len(price_drops)} |\n"
        f"| Disappeared | {len(disappeared)} |\n"
        f"| Price history depth | {depth_note} |\n"
        + excluded_note
    )

    # GPU Price History (per query, suppressed if <5 observations)
    from src.database import open_db, gpu_price_stats, price_context, percentile_rank
    from src.gpu_search import GPU_QUERIES
    try:
        db_conn = open_db()
        for query in GPU_QUERIES:
            stats = gpu_price_stats(db_conn, query)
            if stats is None:
                continue
            sections.append(
                f"## Price History — \"{query}\" "
                f"(last {stats['days']} days, {stats['count']} observations)\n"
            )
            sections.append(
                f"| Metric | Price |\n"
                f"|---|---|\n"
                f"| Floor (P10) | ${stats['p10']:,.0f} |\n"
                f"| Median (P50) | ${stats['p50']:,.0f} |\n"
                f"| Ceiling (P90) | ${stats['p90']:,.0f} |\n"
                f"| Observed min | ${stats['min']:,.0f} |\n"
                f"| Observed max | ${stats['max']:,.0f} |\n"
            )
            sections.append(f"> {price_context(stats['p50'], stats)}\n")
        db_conn.close()
    except Exception:
        pass

    # New listings
    if new_listings:
        sections.append(f"## New GPU Listings ({len(new_listings)})\n")
        for i, item in enumerate(new_listings, 1):
            sections.append(_gpu_item_block(item, i))
            sections.append("")

    # Priority
    if priority:
        sections.append(f"## Priority (score 70+) — {len(priority)} listing(s)\n")
        for i, item in enumerate(priority, 1):
            sections.append(_gpu_item_block(item, i))
            sections.append("")

    # Review
    if review:
        sections.append(f"## Review (score 55–69) — {len(review)} listing(s)\n")
        for i, item in enumerate(review, 1):
            sections.append(_gpu_item_block(item, i))
            sections.append("")

    # Marginal
    if marginal:
        sections.append(f"## Marginal (score 40–54) — {len(marginal)} listing(s)\n")
        for i, item in enumerate(marginal, 1):
            sections.append(_gpu_item_block(item, i))
            sections.append("")

    # Price drops
    if price_drops:
        sections.append(f"## Price Drops ({len(price_drops)})\n")
        for i, item in enumerate(price_drops, 1):
            old = item.get("old_price", 0)
            curr = item.get("price", 0)
            sections.append(
                f"{i}. **{item.get('title', '')[:80]}**  \n"
                f"   {_fmt_price(old)} → {_fmt_price(curr)} · Score {item.get('score', 0)} · {item.get('url', '')}\n"
            )

    # Disappeared
    if disappeared:
        recent = sorted(disappeared, key=lambda x: x.get("last_seen", ""), reverse=True)[:5]
        sections.append("## Recently Disappeared (sold or pulled)\n")
        for item in recent:
            sections.append(
                f"- {item.get('title', '')[:80]} — "
                f"{_fmt_price(item.get('price', 0))} — "
                f"last seen {_time_ago(item.get('last_seen', ''))}\n"
            )

    if not scored_items and not new_listings:
        sections.append("_No GPU listings met the minimum score threshold this run._\n")

    GPU_REPORT_PATH.write_text("\n".join(sections), encoding="utf-8")
    return GPU_REPORT_PATH

"""
SQLite persistence layer for price history.

Stores one observation per listing per run, enabling the tool to build
its own 90-day price time series without any external data source.

DB location: cache/history.db (gitignored via cache/)
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).parent.parent / "cache"
DB_PATH = CACHE_DIR / "history.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT    NOT NULL,
    search_query TEXT    NOT NULL,
    observed_at  TEXT    NOT NULL,  -- ISO 8601 UTC
    price        REAL    NOT NULL,
    score        INTEGER,
    status       TEXT    NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_price_obs_item
    ON price_observations (item_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_price_obs_query
    ON price_observations (search_query, observed_at);

CREATE TABLE IF NOT EXISTS gpu_price_observations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id      TEXT    NOT NULL,
    search_query TEXT    NOT NULL,
    observed_at  TEXT    NOT NULL,  -- ISO 8601 UTC
    price        REAL    NOT NULL,
    score        INTEGER,
    status       TEXT    NOT NULL DEFAULT 'active'
);

CREATE INDEX IF NOT EXISTS idx_gpu_price_obs_item
    ON gpu_price_observations (item_id, observed_at);

CREATE INDEX IF NOT EXISTS idx_gpu_price_obs_query
    ON gpu_price_observations (search_query, observed_at);
"""


def open_db() -> sqlite3.Connection:
    """Open (or create) the history database and ensure schema exists."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


def record_observation(
    conn: sqlite3.Connection,
    item_id: str,
    search_query: str,
    observed_at: str,
    price: float,
    score: int | None,
    status: str = "active",
    flags: list[str] | None = None,
) -> bool:
    """
    Record a price observation. Returns False (skipped) if flags contain SUSPICIOUS_LOW.
    Anomalous prices must not contaminate the market statistics baseline.
    """
    if flags and "SUSPICIOUS_LOW" in flags:
        return False
    conn.execute(
        """
        INSERT INTO price_observations
            (item_id, search_query, observed_at, price, score, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, search_query, observed_at, price, score, status),
    )
    return True


def mark_disappeared(
    conn: sqlite3.Connection,
    item_id: str,
    observed_at: str,
    search_query: str,
    price: float,
) -> None:
    """Record a final 'disappeared' observation for an item no longer returned."""
    conn.execute(
        """
        INSERT INTO price_observations
            (item_id, search_query, observed_at, price, score, status)
        VALUES (?, ?, ?, ?, NULL, 'disappeared')
        """,
        (item_id, search_query, observed_at, price),
    )


def _percentile(values: list[float], p: float) -> float:
    """Return the p-th percentile (0–100) of a sorted list."""
    if not values:
        return 0.0
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def price_stats(
    conn: sqlite3.Connection,
    search_query: str,
    days: int = 90,
    min_observations: int = 5,
) -> dict[str, Any] | None:
    """
    Compute price statistics for a query over the last N days.

    Returns None if fewer than min_observations exist (suppress in report).
    """
    rows = conn.execute(
        """
        SELECT price FROM price_observations
        WHERE search_query = ?
          AND observed_at >= datetime('now', ? || ' days')
          AND status = 'active'
        ORDER BY price
        """,
        (search_query, f"-{days}"),
    ).fetchall()

    prices = [r["price"] for r in rows]
    if len(prices) < min_observations:
        return None

    return {
        "query": search_query,
        "count": len(prices),
        "min": min(prices),
        "p10": _percentile(prices, 10),
        "p50": _percentile(prices, 50),
        "p90": _percentile(prices, 90),
        "max": max(prices),
        "days": days,
    }


def percentile_rank(price: float, stats: dict[str, Any]) -> float:
    """Return the approximate percentile rank (0–100) of price within stats."""
    p10, p50, p90 = stats["p10"], stats["p50"], stats["p90"]
    mn, mx = stats["min"], stats["max"]
    if price <= mn:
        return 0.0
    if price >= mx:
        return 100.0
    # Linear interpolation across known percentile anchors
    anchors = [(mn, 0), (p10, 10), (p50, 50), (p90, 90), (mx, 100)]
    for i in range(len(anchors) - 1):
        lo_p, lo_pct = anchors[i]
        hi_p, hi_pct = anchors[i + 1]
        if lo_p <= price <= hi_p:
            if hi_p == lo_p:
                return lo_pct
            frac = (price - lo_p) / (hi_p - lo_p)
            return lo_pct + frac * (hi_pct - lo_pct)
    return 50.0


def price_context(price: float, stats: dict[str, Any]) -> str:
    """Return a one-line interpretive comment on where price sits historically."""
    pct = percentile_rank(price, stats)
    if pct <= 15:
        return f"At ${price:,.0f}, this is near the 90-day floor (P{pct:.0f}). Historically a strong price."
    if pct >= 85:
        return f"At ${price:,.0f}, this is near the 90-day ceiling (P{pct:.0f}). Worth waiting unless there is urgency."
    return f"At ${price:,.0f}, this is mid-range for the past 90 days (P{pct:.0f})."


def history_depth_days(conn: sqlite3.Connection) -> int:
    """Return how many calendar days of observations are in the database."""
    row = conn.execute(
        "SELECT CAST(julianday('now') - julianday(MIN(observed_at)) AS INTEGER) AS depth "
        "FROM price_observations"
    ).fetchone()
    if not row or row["depth"] is None:
        return 0
    return max(0, row["depth"])


# ---------------------------------------------------------------------------
# GPU price history — parallel table, identical interface
# ---------------------------------------------------------------------------

def record_gpu_observation(
    conn: sqlite3.Connection,
    item_id: str,
    search_query: str,
    observed_at: str,
    price: float,
    score: int | None,
    status: str = "active",
    flags: list[str] | None = None,
) -> bool:
    """
    Record a GPU price observation. Returns False (skipped) if SUSPICIOUS_LOW.
    Anomalous prices must not contaminate the market statistics baseline.
    """
    if flags and "SUSPICIOUS_LOW" in flags:
        return False
    conn.execute(
        """
        INSERT INTO gpu_price_observations
            (item_id, search_query, observed_at, price, score, status)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (item_id, search_query, observed_at, price, score, status),
    )
    return True


def mark_gpu_disappeared(
    conn: sqlite3.Connection,
    item_id: str,
    observed_at: str,
    search_query: str,
    price: float,
) -> None:
    """Record a final 'disappeared' observation for a GPU listing no longer returned."""
    conn.execute(
        """
        INSERT INTO gpu_price_observations
            (item_id, search_query, observed_at, price, score, status)
        VALUES (?, ?, ?, ?, NULL, 'disappeared')
        """,
        (item_id, search_query, observed_at, price),
    )


def gpu_price_stats(
    conn: sqlite3.Connection,
    search_query: str,
    days: int = 90,
    min_observations: int = 5,
) -> dict[str, Any] | None:
    """Compute GPU price statistics for a query over the last N days."""
    rows = conn.execute(
        """
        SELECT price FROM gpu_price_observations
        WHERE search_query = ?
          AND observed_at >= datetime('now', ? || ' days')
          AND status = 'active'
        ORDER BY price
        """,
        (search_query, f"-{days}"),
    ).fetchall()

    prices = [r["price"] for r in rows]
    if len(prices) < min_observations:
        return None

    return {
        "query": search_query,
        "count": len(prices),
        "min": min(prices),
        "p10": _percentile(prices, 10),
        "p50": _percentile(prices, 50),
        "p90": _percentile(prices, 90),
        "max": max(prices),
        "days": days,
    }


def gpu_history_depth_days(conn: sqlite3.Connection) -> int:
    """Return how many calendar days of GPU observations are in the database."""
    row = conn.execute(
        "SELECT CAST(julianday('now') - julianday(MIN(observed_at)) AS INTEGER) AS depth "
        "FROM gpu_price_observations"
    ).fetchone()
    if not row or row["depth"] is None:
        return 0
    return max(0, row["depth"])

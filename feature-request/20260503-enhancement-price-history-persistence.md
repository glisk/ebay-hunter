# Enhancement Request: Persist Price History Per Listing Per Run

**Date:** 2026-05-03  
**File:** `20260503-enhancement-price-history-persistence.md`  
**Priority:** Medium — no functional regression, but every day without this is 90-day history data we can never recover  
**Component:** Database / storage layer, report generator  

---

## Background

eBay's `findCompletedItems` API — the standard mechanism for querying sold price history — was decommissioned in February 2025. The replacement (Marketplace Insights API) requires eBay Business approval and is not freely available. There is no viable external source for sold price history that doesn't carry ToS risk or a paid subscription.

The hunter is already running on a schedule and accumulating observations. If each run persists the price seen per listing, the database becomes its own 90-day price time series — tuned to our exact search queries and scoring criteria, with no external dependencies.

This data does not exist if we don't start storing it now. Every run that discards price observations is history we cannot reconstruct.

---

## Requested Changes

### 1. Database Schema — Add Price Observation Table

Add a `price_observations` table (or equivalent structure) that records one row per listing per run:

```sql
CREATE TABLE price_observations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id         TEXT NOT NULL,          -- eBay item ID
    search_query    TEXT NOT NULL,          -- the query that surfaced it
    observed_at     TIMESTAMP NOT NULL,     -- UTC timestamp of this run
    price           DECIMAL(10,2) NOT NULL, -- listed price at time of observation
    score           INTEGER,                -- score at time of observation
    status          TEXT DEFAULT 'active'   -- 'active', 'disappeared', 'price_drop'
);

CREATE INDEX idx_price_obs_item ON price_observations(item_id, observed_at);
CREATE INDEX idx_price_obs_query ON price_observations(search_query, observed_at);
```

The `status` field should be set to `disappeared` on the first run where a previously-seen item is no longer returned. This is our proxy for "sold or expired" — imperfect but useful signal.

### 2. Run Logic — Record Observation on Every Run

On each run, for every listing that is fetched and passes dedup/discard filters, write one row to `price_observations` before scoring. This ensures we capture price even for listings that fall below the score threshold.

```python
def record_observation(db, item_id, search_query, price, score, status="active"):
    db.execute("""
        INSERT INTO price_observations 
            (item_id, search_query, observed_at, price, score, status)
        VALUES (?, ?, datetime('now'), ?, ?, ?)
    """, (item_id, search_query, price, score, status))
```

For listings present in the previous run but absent in the current run, write a final row with `status = 'disappeared'` before removing them from the active listings table.

### 3. Price History Statistics — Compute at Report Time

At report time, compute the following for each active search query using the last 90 days of observations:

```python
def price_stats(db, search_query, days=90):
    rows = db.execute("""
        SELECT price FROM price_observations
        WHERE search_query = ?
          AND observed_at >= datetime('now', '-? days')
          AND status = 'active'
        ORDER BY price
    """, (search_query, days)).fetchall()

    prices = [r[0] for r in rows]
    if len(prices) < 5:
        return None  # insufficient history, don't report

    return {
        "count": len(prices),
        "min": min(prices),
        "p10": percentile(prices, 10),
        "p50": percentile(prices, 50),
        "p90": percentile(prices, 90),
        "max": max(prices),
        "days_of_history": days
    }
```

Return `None` and suppress the section if fewer than 5 observations exist — don't display statistics that aren't meaningful yet.

### 4. Report Output — Add Price History Section

Add a **Price History** section to the `--report` output, appearing once per search query, above the scored listings:

```
## Price History — "5975WX workstation" (last 90 days, 47 observations)

| Metric | Price |
|---|---|
| Floor (P10) | $1,650 |
| Median (P50) | $1,775 |
| Ceiling (P90) | $1,900 |
| Observed min | $1,599 |
| Observed max | $2,100 |

> Current listings at $1,750 are near the 90-day floor. No urgency to act, 
> but this is historically a good price point for this configuration.
```

The interpretive line should be generated as a simple conditional, not free text:

```python
def price_context(current_price, stats):
    p = percentile_rank(current_price, stats)
    if p <= 15:
        return f"At ${current_price}, this listing is near the 90-day floor (P{p:.0f}). Historically a strong price."
    elif p >= 85:
        return f"At ${current_price}, this listing is near the 90-day ceiling (P{p:.0f}). Worth waiting unless urgency."
    else:
        return f"At ${current_price}, this listing is mid-range for the past 90 days (P{p:.0f})."
```

---

## What This Does Not Require

- No external API calls
- No eBay developer account changes
- No scraping
- No paid data service

The only inputs are observations the hunter is already fetching on every run. This is purely a persistence and reporting change.

---

## Rollout Note

The price history section should be **silently suppressed** in the report until at least 5 observations exist for a given query. Add a note to the run summary indicating how many days of history are currently accumulated:

```
| Price history depth | 12 days (90 days needed for full signal) |
```

This lets us track progress toward meaningful statistics without displaying misleading data during the accumulation period.

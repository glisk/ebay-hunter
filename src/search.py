"""
eBay Browse API search layer.

Runs all configured queries, paginates up to 200 results each,
and deduplicates by eBay item ID.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .auth import get_auth_headers, _base_url, REQUESTS_VERIFY

# ---------------------------------------------------------------------------
# Query configuration
# ---------------------------------------------------------------------------

QUERIES: list[str] = [
    # Platform-specific
    "ThinkStation P620 Threadripper PRO 5000",
    "Precision 7865 Threadripper PRO",
    "HP Z6 G5 Threadripper 5000",
    # CPU-specific
    "5965WX workstation",
    "5975WX workstation",
    "5945WX workstation",
    "5955WX workstation",
    # Broad catch
    "Threadripper PRO 5000 workstation 128GB",
    "WRX80 workstation tower",
]

RESULTS_PER_PAGE = 50
MAX_RESULTS_PER_QUERY = 200  # 4 pages of 50
MAX_PAGES = MAX_RESULTS_PER_QUERY // RESULTS_PER_PAGE

# If fewer than this many results on a page pass the discard prefilter, stop
# paginating that query (relevance degradation heuristic).
EARLY_STOP_THRESHOLD = 3

# Rate-limit pause between page requests (seconds)
PAGE_DELAY = 0.25


def _build_filter(max_price: float = 2000.0) -> str:
    """
    Build the eBay filter parameter string.

    We request USED and SELLER_REFURBISHED conditions, USD prices up to
    max_price, and US-located items.
    """
    return (
        f"conditions:{{USED|SELLER_REFURBISHED}},"
        f"price:[0..{int(max_price)}],"
        f"priceCurrency:USD,"
        f"itemLocationCountry:US"
    )


def _fetch_page(
    query: str,
    offset: int,
    max_price: float,
    headers: dict,
    sandbox: bool,
) -> dict[str, Any]:
    """
    Fetch a single page of results from the Browse API.

    Returns the parsed JSON response dict, or an empty dict on error.
    """
    base = _base_url(sandbox)
    url = f"{base}/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": _build_filter(max_price),
        "sort": "newlyListed",
        "limit": str(RESULTS_PER_PAGE),
        "offset": str(offset),
    }
    try:
        resp = requests.get(
            url,
            headers=headers,
            params=params,
            verify=REQUESTS_VERIFY,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.HTTPError as exc:
        # Surface but don't crash — we'll simply get no results for this page
        print(f"[search] HTTP error for query '{query}' offset {offset}: {exc}")
        return {}
    except requests.RequestException as exc:
        print(f"[search] Request error for query '{query}' offset {offset}: {exc}")
        return {}


def _extract_items(response: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the itemSummaries list from an API response."""
    return response.get("itemSummaries", [])


def _normalize_item(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Flatten a raw eBay itemSummary into a consistent internal dict.

    Confirmed present in Browse API summary responses (verified against
    production API 2026-05-03):
    - seller.feedbackPercentage, seller.feedbackScore — no per-item call needed
    - shippingOptions[] with shippingCostType and shippingCost
    - itemLocation.country for seller location filtering
    """
    price_value = 0.0
    price_obj = raw.get("price", {})
    if price_obj:
        try:
            price_value = float(price_obj.get("value", 0))
        except (TypeError, ValueError):
            price_value = 0.0

    seller = raw.get("seller", {})
    feedback_pct = None
    feedback_score = None
    raw_pct = seller.get("feedbackPercentage")
    raw_score = seller.get("feedbackScore")
    if raw_pct is not None:
        try:
            feedback_pct = float(raw_pct)
        except (TypeError, ValueError):
            feedback_pct = None
    if raw_score is not None:
        try:
            feedback_score = int(raw_score)
        except (TypeError, ValueError):
            feedback_score = None

    # Shipping / local pickup
    # Browse API may expose this as a list of shippingOptions
    shipping_options = raw.get("shippingOptions", [])
    local_pickup = raw.get("localPickup", False)
    if not local_pickup:
        for opt in shipping_options:
            if opt.get("shippingServiceCode") in ("PICKUP", "LOCAL_PICKUP"):
                local_pickup = True
                break

    # Buying options (FIXED_PRICE, AUCTION, BEST_OFFER)
    buying_options = raw.get("buyingOptions", [])

    # Item location
    location = raw.get("itemLocation", {})
    location_str = location.get("city", "")
    state = location.get("stateOrProvince", "")
    country = location.get("country", "")
    if state:
        location_str = f"{location_str}, {state}" if location_str else state
    if country and country != "US":
        location_str = f"{location_str} ({country})" if location_str else country

    return {
        "item_id": raw.get("itemId", ""),
        "title": raw.get("title", ""),
        "price": price_value,
        "currency": price_obj.get("currency", "USD"),
        "condition": raw.get("condition", ""),
        "seller_username": seller.get("username", ""),
        "seller_feedback_pct": feedback_pct,
        "seller_feedback_score": feedback_score,
        "buying_options": buying_options,
        "local_pickup": local_pickup,
        "location": location_str,
        "url": raw.get("itemWebUrl", ""),
        "image_url": (raw.get("image") or {}).get("imageUrl", ""),
        "short_description": raw.get("shortDescription", ""),
        # Time left is present for auctions
        "time_left": raw.get("itemEndDate", ""),
        # Raw item for any downstream field access
        "_raw": raw,
    }


def run_all_queries(
    sandbox: bool = False,
    max_price: float = 2000.0,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """
    Run all QUERIES, paginate, normalize, and deduplicate results.

    Args:
        sandbox: Use eBay sandbox environment.
        max_price: Price ceiling passed to the eBay filter.
        force_refresh: Force OAuth token refresh before searching.

    Returns:
        A tuple of:
          - deduplicated list of normalized item dicts
          - dict mapping item_id -> list of query strings that matched it
            (useful for noting multi-query hits in output)
    """
    headers = get_auth_headers(sandbox=sandbox, force_refresh=force_refresh)

    # item_id -> normalized item
    seen: dict[str, dict[str, Any]] = {}
    # item_id -> list of matching queries
    query_hits: dict[str, list[str]] = {}

    for query in QUERIES:
        for page in range(MAX_PAGES):
            offset = page * RESULTS_PER_PAGE
            if page > 0:
                time.sleep(PAGE_DELAY)

            response = _fetch_page(query, offset, max_price, headers, sandbox)
            items = _extract_items(response)

            if not items:
                break  # No more results for this query

            # Early-stop heuristic: count how many items on this page have
            # a title that contains at least one of our target keywords.
            # If very few do, the query has drifted off-topic.
            relevant_count = sum(
                1 for item in items
                if any(
                    kw in item.get("title", "").upper()
                    for kw in ("5945WX", "5955WX", "5965WX", "5975WX", "5995WX",
                               "THREADRIPPER", "P620", "7865", "Z6 G5", "WRX80")
                )
            )
            if page > 0 and relevant_count < EARLY_STOP_THRESHOLD:
                break  # Relevance degraded — stop paginating this query

            for raw_item in items:
                item = _normalize_item(raw_item)
                iid = item["item_id"]
                if not iid:
                    continue
                if iid not in seen:
                    seen[iid] = item
                    query_hits[iid] = [query]
                else:
                    query_hits[iid].append(query)

    return list(seen.values()), query_hits


# Keep fetch_all as an alias for backward compatibility
fetch_all = run_all_queries

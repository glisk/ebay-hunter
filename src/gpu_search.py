"""
eBay Browse API search layer — RTX 3090 GPU hunter.

Runs all GPU_QUERIES, paginates up to 100 results each,
and deduplicates by eBay item ID. Separate from workstation search.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .auth import get_auth_headers, _base_url, REQUESTS_VERIFY

# ---------------------------------------------------------------------------
# Query configuration
# ---------------------------------------------------------------------------

GPU_QUERIES: list[str] = [
    "RTX 3090 24GB",
    "GeForce 3090 24GB",
    "RTX 3090 founders edition",
    "RTX 3090 ASUS",
    "RTX 3090 EVGA",
    "RTX 3090 MSI",
    "RTX 3090 Gigabyte",
    "RTX 3090 Zotac",
    "RTX 3090 PNY",
    "RTX 3090 NVLink bridge",
]

# The NVLink query may surface standalone bridge accessories — these need
# an extra relevance check to ensure "3090" appears in the title.
NVLINK_QUERY = "RTX 3090 NVLink bridge"

GPU_RESULTS_PER_PAGE = 50
GPU_MAX_RESULTS_PER_QUERY = 100  # 2 pages of 50 — GPU market is denser
GPU_MAX_PAGES = GPU_MAX_RESULTS_PER_QUERY // GPU_RESULTS_PER_PAGE

GPU_PRICE_MIN = 350
GPU_PRICE_MAX = 1000

PAGE_DELAY = 0.25


def _build_gpu_filter(max_price: float = GPU_PRICE_MAX) -> str:
    return (
        f"conditions:{{USED|SELLER_REFURBISHED}},"
        f"price:[{GPU_PRICE_MIN}..{int(max_price)}],"
        f"priceCurrency:USD,"
        f"itemLocationCountry:US"
    )


def _extract_return_policy(raw: dict[str, Any]) -> str:
    terms = raw.get("returnTerms", {})
    if not terms or not terms.get("returnsAccepted"):
        return "No returns"
    period = terms.get("returnPeriod", {})
    days = period.get("value")
    if days:
        return f"{days}-day returns"
    return "Returns accepted"


def _fetch_gpu_page(
    query: str,
    offset: int,
    max_price: float,
    headers: dict,
    sandbox: bool,
) -> dict[str, Any]:
    base = _base_url(sandbox)
    url = f"{base}/buy/browse/v1/item_summary/search"
    params = {
        "q": query,
        "filter": _build_gpu_filter(max_price),
        "sort": "newlyListed",
        "limit": str(GPU_RESULTS_PER_PAGE),
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
        print(f"[gpu_search] HTTP error for query '{query}' offset {offset}: {exc}")
        return {}
    except requests.RequestException as exc:
        print(f"[gpu_search] Request error for query '{query}' offset {offset}: {exc}")
        return {}


def _normalize_gpu_item(raw: dict[str, Any]) -> dict[str, Any]:
    """Flatten a raw eBay itemSummary into the GPU item internal dict."""
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

    shipping_options = raw.get("shippingOptions", [])
    local_pickup = raw.get("localPickup", False)
    if not local_pickup:
        for opt in shipping_options:
            if opt.get("shippingServiceCode") in ("PICKUP", "LOCAL_PICKUP"):
                local_pickup = True
                break

    buying_options = raw.get("buyingOptions", [])

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
        "time_left": raw.get("itemEndDate", ""),
        "return_policy": _extract_return_policy(raw),
        "_raw": raw,
    }


def run_gpu_queries(
    sandbox: bool = False,
    max_price: float = GPU_PRICE_MAX,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    """
    Run all GPU_QUERIES, paginate, normalize, and deduplicate results.

    Returns:
        A tuple of:
          - deduplicated list of normalized GPU item dicts
          - dict mapping item_id -> list of query strings that matched it
    """
    headers = get_auth_headers(sandbox=sandbox, force_refresh=force_refresh)

    seen: dict[str, dict[str, Any]] = {}
    query_hits: dict[str, list[str]] = {}

    for query in GPU_QUERIES:
        is_nvlink_query = query == NVLINK_QUERY

        for page in range(GPU_MAX_PAGES):
            offset = page * GPU_RESULTS_PER_PAGE
            if page > 0:
                time.sleep(PAGE_DELAY)

            response = _fetch_gpu_page(query, offset, max_price, headers, sandbox)
            items = response.get("itemSummaries", [])

            if not items:
                break

            # Early-stop: GPU relevance check
            relevant_count = sum(
                1 for item in items
                if "3090" in item.get("title", "").upper()
                or "RTX" in item.get("title", "").upper()
            )
            if page > 0 and relevant_count < 3:
                break

            for raw_item in items:
                item = _normalize_gpu_item(raw_item)
                iid = item["item_id"]
                if not iid:
                    continue

                # NVLink query: discard if "3090" not in title — standalone bridge
                if is_nvlink_query and "3090" not in item["title"].upper():
                    continue

                if iid not in seen:
                    seen[iid] = item
                    query_hits[iid] = [query]
                else:
                    query_hits[iid].append(query)

    return list(seen.values()), query_hits

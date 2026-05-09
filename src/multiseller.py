"""
Multi-storefront seller detection.

A single operator running multiple eBay accounts creates false market depth:
the same inventory appears as independent supply and the same price is
recorded multiple times per run in the price history.

Detection uses a 2-of-3 signal heuristic across active scored items:
  1. Same city (from the location field)
  2. Identical base price (to the cent)
  3. Identical variant price signature (sorted prices across all variants)

Signal 3 is only available when variant_data has been populated by
search.enrich_variant_items(). Without it, city + price (2 signals) is
sufficient — an exact price coincidence in the same city across 3+ listings
is essentially conclusive for workstation-grade hardware.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any


def _city(location: str) -> str:
    """Extract the city portion from 'City, State' or return the whole string."""
    return location.split(",")[0].strip().lower()


def _variant_price_sig(item: dict[str, Any]) -> tuple[float, ...] | None:
    """Sorted tuple of variant prices, or None if no variant data."""
    vd = item.get("variant_data")
    if not vd:
        return None
    prices = tuple(sorted(v["price"] for v in vd if v.get("price", 0) > 0))
    return prices if prices else None


def _count_signals(a: dict[str, Any], b: dict[str, Any]) -> int:
    """Count how many same-operator signals match between two listings."""
    count = 0

    city_a = _city(a.get("location", ""))
    city_b = _city(b.get("location", ""))
    if city_a and city_a == city_b:
        count += 1

    price_a = a.get("price", 0.0)
    price_b = b.get("price", 0.0)
    if price_a > 0 and price_a == price_b:
        count += 1

    sig_a = _variant_price_sig(a)
    sig_b = _variant_price_sig(b)
    if sig_a is not None and sig_a == sig_b:
        count += 1

    return count


SIGNAL_THRESHOLD = 2


def find_groups(items: list[dict[str, Any]]) -> list[list[str]]:
    """
    Find clusters of item_ids that appear to be the same operator.

    Uses Union-Find to build connected components — if A matches B and
    B matches C they all belong to one group even if A and C don't
    directly match.

    Returns a list of groups, each group being a list of item_ids.
    Only groups with 2+ members are returned.
    """
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    for i in range(n):
        for j in range(i + 1, n):
            if _count_signals(items[i], items[j]) >= SIGNAL_THRESHOLD:
                union(i, j)

    groups: dict[int, list[str]] = defaultdict(list)
    for i, item in enumerate(items):
        groups[find(i)].append(item["item_id"])

    return [g for g in groups.values() if len(g) >= 2]


def apply_storefront_flags(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Flag listings that appear to be multiple storefronts for the same operator.

    Adds MULTI_STOREFRONT_CANDIDATE to the flags list of each affected item
    and sets related_storefront_ids (list of the other item IDs in the group).

    Returns a new list — does not mutate input items.
    """
    groups = find_groups(items)
    if not groups:
        return list(items)

    # Build a lookup: item_id -> sibling item_ids
    siblings: dict[str, list[str]] = {}
    for group in groups:
        for iid in group:
            siblings[iid] = [x for x in group if x != iid]

    result = []
    for item in items:
        iid = item.get("item_id", "")
        if iid in siblings:
            item = dict(item)
            flags = list(item.get("flags", []))
            if "MULTI_STOREFRONT_CANDIDATE" not in flags:
                flags.append("MULTI_STOREFRONT_CANDIDATE")
            item["flags"] = flags
            item["related_storefront_ids"] = siblings[iid]
        result.append(item)

    return result

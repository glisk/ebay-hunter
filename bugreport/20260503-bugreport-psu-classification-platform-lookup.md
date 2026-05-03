# Bug Report: PSU Classification Incorrectly Scores Known-Good Platforms as YELLOW

**Date:** 2026-05-03  
**File:** `20260503-bugreport-psu-classification-platform-lookup.md`  
**Severity:** Medium — scoring inaccuracy, not a crash  
**Component:** PSU classifier / scoring engine  

---

## Summary

The PSU classification logic treats all listings with no explicit wattage mention in the title or description as YELLOW (unknown), awarding 10/20 points. For the Lenovo ThinkStation P620, this is incorrect. Lenovo's official product specification database confirms that **every P620 SKU ships with a 1000W Platinum Fixed PSU**, regardless of CPU, RAM, or GPU configuration. The tool has enough information to classify P620 listings as GREEN without any mention of wattage in the listing text.

As a result, all Priority-tier P620 listings in the current report score 78/100 when the correct score is 88/100.

---

## Evidence

Source: Lenovo ThinkStation P620 multi-model specification export (two xlsx files, dated 2026-04-28), covering hundreds of SKUs across all CPU variants (3945WX through 5995WX), all regions, and all GPU configurations.

**Power Supply column value across every single row: `1000W Platinum Fixed`**

No exceptions were found in the dataset. This is a platform-level constant, not a per-SKU variable.

---

## Current Behavior

```
Listing: "Lenovo P620 32-Core AMD THREADRIPPER PRO 5975WX, 128GB DDR4, NO Storage/GPU/OS"
PSU classification: YELLOW (no wattage mention in title/description)
PSU score: 10/20
Total score: 78/100
```

---

## Expected Behavior

```
Listing: "Lenovo P620 32-Core AMD THREADRIPPER PRO 5975WX, 128GB DDR4, NO Storage/GPU/OS"
PSU classification: GREEN (platform lookup confirms 1000W)
PSU score: 20/20
Total score: 88/100
```

---

## Recommended Fix

Add a platform PSU lookup table to the classifier. When no wattage is found in listing text, fall back to the known platform spec before defaulting to YELLOW.

```python
# Platform PSU lookup — sourced from manufacturer spec databases
# Values represent confirmed minimum PSU wattage for the platform
PLATFORM_PSU_WATTAGE = {
    "P620": 1000,        # Confirmed: Lenovo spec DB, all SKUs, 1000W Platinum Fixed
    "Precision 7865": None,   # Not yet verified — leave as YELLOW fallback
    "HP Z6 G5": None,         # Not yet verified — leave as YELLOW fallback
}

def classify_psu(title: str, description: str, platform: str) -> tuple[str, str]:
    """
    Returns (classification, source) where classification is GREEN/YELLOW/RED
    and source indicates whether the classification came from listing text or platform lookup.
    """
    text = (title + " " + description).upper()

    # Check listing text first — explicit mention always wins
    if any(w in text for w in ["900W", "1000W", "1200W", "1KW"]):
        return "GREEN", "listing_text"
    if "450W" in text:
        return "RED", "listing_text"

    # Fall back to platform lookup
    known_wattage = PLATFORM_PSU_WATTAGE.get(platform)
    if known_wattage and known_wattage >= 900:
        return "GREEN", "platform_spec"

    # Truly unknown
    return "YELLOW", "unknown"
```

The `source` field should be stored in the result object and surfaced in the report output so it's visible which listings were classified by platform spec vs. explicit listing text. Example output:

```
PSU: GREEN (platform spec — 1000W confirmed for P620)
```

vs.

```
PSU: GREEN (listing text)
```

---

## Scope of Impact

- All Lenovo ThinkStation P620 listings currently scoring YELLOW on PSU
- In the 2026-05-03 report: all 5 Priority listings and the 3 Review listings are affected
- Corrected scores: Priority listings move from 78 → 88; Review listings recalculate accordingly

---

## Additional Notes

The Dell Precision 7865 and HP Z6 G5 A PSU configurations should be independently verified against their respective spec databases before adding to the lookup table. Do not assume — confirm from manufacturer documentation the same way P620 was confirmed. Once verified, add with a source comment matching the pattern above.

This lookup table approach is also the right foundation for any future platform-specific constants (e.g., known PCIe slot counts, confirmed ECC support, known chassis limitations).

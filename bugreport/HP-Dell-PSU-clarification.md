# HP & Dell PSU Configuration Research — Clarification

**Date:** 2026-05-03  
**Purpose:** Verify whether HP Z6 G5 A and Dell Precision 7865 PSU configurations can be treated as platform constants, as was confirmed for the Lenovo ThinkStation P620.

---

## Summary Finding

Unlike the Lenovo P620 — which ships with a fixed 1000W PSU across every SKU — both the Dell Precision 7865 and HP Z6 G5 A offer **multiple PSU options that vary by configuration**. Neither platform can be added to the platform lookup table as a constant. YELLOW (unknown) remains the correct classification for listings that do not state wattage explicitly.

---

## Dell Precision 7865

**Source:** Dell Precision 7865 Tower Service Manual (official Dell documentation)

The service manual explicitly documents two PSU variants within the same chassis. The installation procedure reads:

- *"For 1000W PSU: Connect two of the 6-pin ATX CPU power cables to the ATX CPU1 and ATX CPU2 connectors on the system board."*
- *"For 1300W PSU: Connect three of the 6-pin ATX CPU power cables to the ATX CPU1, ATX CPU2 and ATX CPU3 connectors on the system board."*

Retail listings and third-party reviews confirm 1350W as the most common configuration shipped. The StorageReview.com review of the 7865 specifically notes the 1350W PSU as required for dual-GPU configurations (two RTX A6000 48GB cards).

**Conclusion:** PSU is configuration-dependent. Cannot be treated as a platform constant. The minimum documented option (1000W) is technically adequate for a single GPU, but a used listing without stated wattage cannot be safely assumed to carry that configuration. YELLOW classification is correct.

---

## HP Z6 G5 A

**Source:** HP Z6 G5 A QuickSpecs (official HP documentation, December 2023)

The QuickSpecs document explicitly lists **four PSU tiers** available for the Z6 G5 A:

| PSU Wattage | Notes |
|---|---|
| 775W | Base / entry configuration |
| 1125W | Mid-tier |
| 1275W | Higher GPU configurations |
| 1450W | Required for select high-end GPU configurations |

The document includes specific notes such as: *"Note 5: Only supported with 1125W/1275W and 1450W PSUs"* for certain GPU options, confirming that the 775W configuration exists and is actively sold.

**Important distinction:** The Z6 G5 A (AMD Threadripper PRO) is a different product from the Z6 G5 (Intel Xeon W). The hunter tool searches for the Z6 G5 A specifically. Both have variable PSU configurations.

**Conclusion:** PSU is configuration-dependent across a wide range (775W–1450W). A used listing with no stated wattage could carry a 775W PSU, which is inadequate for a high-TDP GPU. YELLOW classification is correct and important here — unlike the Dell, the HP floor is genuinely problematic.

---

## Impact on Platform Lookup Table

The bug fix in `20260503-bugreport-psu-classification-platform-lookup.md` should be updated to reflect this research. The `None` entries are not placeholders pending future research — they represent the verified answer:

```python
PLATFORM_PSU_WATTAGE = {
    "P620": 1000,           # CONFIRMED: Lenovo spec DB, fixed 1000W Platinum across all SKUs
    "Precision 7865": None, # VERIFIED variable: 1000W and 1300W options documented in service manual
    "HP Z6 G5 A": None,     # VERIFIED variable: 775W/1125W/1275W/1450W options in QuickSpecs
}
```

The comment text matters here. Future maintainers should understand that `None` for Dell and HP is a researched conclusion, not an open question.

---

## Why the P620 Is the Outlier

Lenovo's decision to use a single fixed PSU across all P620 SKUs — regardless of CPU, RAM, or GPU configuration — is unusual. The P620 was designed with enough headroom (1000W) that Lenovo never needed to offer a lower-tier option. Dell and HP both tiered their PSU offerings to hit lower price points on entry configurations, which is why their used market carries genuine PSU uncertainty.

This distinction is worth documenting because it explains why the platform lookup approach works cleanly for the P620 and cannot be extended to the other platforms without per-listing verification.

# eBay GPU Hunter — RTX 3090 Search Spec

*Companion to `ebay_hunter_spec.md`. Read that document first — this spec inherits all conventions, stack, auth, API patterns, and git/branch strategy defined there. This document specifies only what is different or additive for the GPU search profile.*

---

## Purpose

Build a parallel search module for RTX 3090 24GB GPUs running alongside the existing workstation hunter. The GPU search and workstation search share the same auth layer, API client, and run scheduler, but maintain completely separate scoring models, discard rules, cache files, and output sections.

This search is currently **market intelligence only**. The purchase decision comes after the target workstation (P620 / 5975WX / 128GB) is confirmed operational. Do not treat urgency signals as purchase triggers — surface them as information.

---

## Separation Requirements

This is non-negotiable. The two search profiles must not pollute each other's data.

| Resource | Workstation Hunter | GPU Hunter |
|---|---|---|
| Cache file | `cache/results.json` | `cache/gpu_results.json` |
| High-priority file | `cache/high-priority.json` | `cache/gpu-high-priority.json` |
| Run log | `cache/run-log.json` | `cache/gpu-run-log.json` |
| Price history table | `price_observations` (existing) | `gpu_price_observations` (new table) |
| Output section | WORKSTATION RESULTS | GPU RESULTS |

Both profiles write to the same SQLite database file if one is in use, but in separate tables. If the workstation hunter uses flat JSON files, the GPU hunter must also use flat JSON files — match the persistence mechanism exactly, do not introduce a new one.

---

## Target Hardware

**RTX 3090 24GB only.**

Explicit exclusions — discard automatically if detected in title or description:
- RTX 3090 **Ti** (different card, higher price, not the target)
- RTX 3080 (12GB — wrong VRAM tier)
- RTX 3080 Ti (12GB — wrong VRAM tier)
- RTX 4090, RTX 4080, or any 40-series mention
- Any mention of "16GB", "12GB", or "10GB" in the GPU context
- Quadro RTX 6000 (different product, different market)
- CMP (Crypto Mining Processor) variants — no display output, useless for this purpose

Accept: all AIB partner variants (ASUS, EVGA, MSI, Gigabyte, Zotac, PNY, Inno3D) and the NVIDIA Founders Edition. Do not prefer one AIB over another in scoring — all are acceptable.

---

## Search Query Strategy

```python
GPU_QUERIES = [
    "RTX 3090 24GB",
    "GeForce 3090 24GB",
    "RTX 3090 founders edition",
    "RTX 3090 ASUS",
    "RTX 3090 EVGA",
    "RTX 3090 MSI",
    "RTX 3090 Gigabyte",
    "RTX 3090 Zotac",
    "RTX 3090 PNY",
]
```

Apply eBay filter: `conditions:{USED|SELLER_REFURBISHED},price:[350..1000],priceCurrency:USD,itemLocationCountry:US`

Deduplicate by item ID before scoring. A card listed under multiple queries counts once.

Paginate to a maximum of 100 results per query (2 pages of 50). GPU listings are denser and less varied than workstation listings — 100 per query is sufficient.

---

## Automatic Discard Conditions

Discard silently (do not show in output, do not write to cache):

- Title or description explicitly mentions RTX 3090 **Ti**
- Title or description mentions 12GB, 16GB in GPU context
- Condition listed as "For parts/not working"
- Seller is outside the United States
- **Seller feedback below 98%** *(stricter than workstation threshold of 95% — GPU fraud profile is higher)*
- **Seller transaction count below 50** *(stricter than workstation threshold of 10 — individual sellers with thin history are higher risk in the GPU market)*
- Format is Auction with less than 24 hours remaining and no Buy It Now option *(stricter than workstation — GPU auctions attract shill bidding)*
- Price above $1,000
- Price below $350 *(likely component, damaged, or scam — below the floor where any legitimate 3090 appears)*
- CMP variant detected in title

---

## Mining Disclosure Handling

Mining history is a **flag, not a discard condition.**

Rationale: a disclosed mining card is better information than an undisclosed one. A seller who states "used for mining, fans replaced, thermal paste refreshed" has given you more actionable information than a seller who says nothing. The card may be perfectly functional. The flag surfaces it for manual review; the human decides.

Mining signal detection — add `MINING_DISCLOSED` flag if any of the following appear in title or description:
- "mining", "mined", "crypto", "ethereum", "ETH"
- "used for compute", "24/7", "datacenter use"
- "fans replaced", "fan replacement" (mining correlate — fans are first to fail)
- "bios modified", "mining bios", "custom bios" — add both `MINING_DISCLOSED` and `BIOS_MODIFIED` flags; display both clearly
- "thermal paste replaced", "repasted" — neutral to positive signal on its own, flag as `REPASTED` for information

Scoring impact of mining flags:
- `MINING_DISCLOSED` alone: -5 points (transparency is a partial offset)
- `BIOS_MODIFIED`: additional -10 points (BIOS modification complicates resale and may affect stability)
- `REPASTED` alone (no other mining signals): 0 points (maintenance, not damage)

**Do not combine these into a single penalty.** Apply each independently so the score breakdown is auditable.

---

## Fraud Signals Specific to GPU Market

The GPU used market has a different fraud profile than the workstation market. Apply these additional checks:

### SUSPICIOUS_LOW flag
Apply if price is below $500 for a card with no explanation. Threshold is higher than it sounds — legitimate 3090s rarely clear below $550 in working condition. At $400–499 the probability of misrepresentation, damage, or scam is elevated. Surface with flag, do not discard.

### Photo mismatch signal (title-based heuristic only — no image analysis)
If the title says "RTX 3090" but also mentions a different card model number (e.g., "RTX 3080" appearing elsewhere in the same listing text), add `TITLE_INCONSISTENCY` flag. This catches listings where the seller is using a popular search term for a different card.

### Stock photo signal
If the description contains phrases like "image for illustration only", "stock photo", "actual item may differ", add `NO_ACTUAL_PHOTO` flag. GPU condition is highly visual — listings without actual photos of the card carry higher risk.

### Return policy as signal (not a scoring criterion, informational only)
Extract and display return policy in listing output: "30-day returns", "No returns", "Seller pays return shipping", etc. Not scored, but shown. A no-returns GPU listing combined with mining disclosure is a meaningful compound risk signal the human should see.

---

## Scoring Model

Each GPU listing scores 0–100. Listings below 40 are discarded silently.

| Criterion | Max Points | Scoring Logic |
|---|---|---|
| Card confirmed as RTX 3090 24GB (not Ti, not 3080) | 30 | 30 if confirmed from title, 15 if ambiguous, 0 if wrong card detected |
| Seller qualification | 20 | 20 if ≥99.5% feedback + ≥100 transactions; 15 if ≥99% + ≥50 transactions; 10 if ≥98% + ≥50 transactions; 0 below thresholds (these listings are already discarded) |
| Price vs. expected range | 20 | See pricing model below |
| Condition and disclosure quality | 15 | See below |
| Mining flags | Up to -15 | Applied as penalties per flag as defined above |
| NVLink bridge included | 5 | 5 if NVLink bridge mentioned or shown in photos; 0 otherwise |
| Return policy | 5 | 5 if 30-day returns; 3 if 14-day returns; 0 if no returns |
| Local pickup available | 5 | 5 if local pickup offered, 0 otherwise |

**Total base: 100 points. Mining penalties reduce from base. Minimum displayed score: 0.**

### Condition and Disclosure Quality (15 points)

| Signal | Points |
|---|---|
| Seller explicitly states tested and working, provides photos of actual card | 15 |
| Seller states tested and working, no explicit photo confirmation | 10 |
| Seller refurbished condition (eBay condition field) | 8 |
| Used, no condition statement beyond eBay "Used" field | 5 |
| "As-is", "untested", or "sold as-is" in description | 0 |

These are additive only from the highest matching tier — do not add multiple rows.

---

## Pricing Model

Current market (May 2026): used RTX 3090 24GB trades at $600–$800 for clean condition from established sellers.

| Condition | Expected Range | Suspicious Low | Overpriced Above |
|---|---|---|---|
| Standard used / unknown condition | $600–$800 | <$500 | >$900 |
| With NVLink bridge | $650–$875 | <$550 | >$1,000 |
| Seller refurbished | $700–$950 | <$600 | >$1,000 |

Price score logic (same pattern as workstation hunter):
- Within expected range: 20 points
- Up to 15% below low end: 20 points (potential deal, check flags carefully)
- Suspicious low (below suspicious threshold): 10 points + `SUSPICIOUS_LOW` flag
- Up to 15% above high end: 10 points
- Overpriced (above ceiling): 0 points

---

## NVLink Bridge

The P620 platform (WRX80) supports NVLink for dual-GPU configurations. A 3090 NVLink bridge is a small accessory (~$30–80 new) but is increasingly hard to source as supply dries up.

If a listing includes an NVLink bridge:
- Add 5 points to score (as defined in scoring model above)
- Add `NVLINK_INCLUDED` flag
- Display prominently in output — this is a meaningful value-add

Run an additional correlated search query: `"RTX 3090" "NVLink bridge"` — include results in the same GPU search pool, subject to the same discard and scoring rules. If the bridge-specific query surfaces a standalone bridge listing (no GPU), discard it.

---

## Priority Tiers

Same tier boundaries as workstation hunter:

- **70–100:** PRIORITY — surface immediately, write to `cache/gpu-high-priority.json`
- **55–69:** REVIEW — worth manual examination
- **40–54:** MARGINAL — listed but deprioritized
- **<40:** Discarded, not shown

---

## Output

### Terminal output

GPU results appear in a separate section below workstation results, clearly delineated:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
GPU RESULTS — RTX 3090 Market Intelligence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[Note: market intelligence only — purchase decision pending workstation confirmation]
```

Each GPU listing displays:
- Score and tier
- Price
- Card model (as detected from title)
- Condition tier
- Seller feedback % and transaction count
- Active flags (MINING_DISCLOSED, BIOS_MODIFIED, SUSPICIOUS_LOW, NVLINK_INCLUDED, etc.)
- Return policy
- Local pickup
- Direct eBay URL

### Price history section

Appears above GPU listings, same format as workstation price history section. Uses `gpu_price_observations` table. Suppress until 5+ observations exist.

---

## CLI Integration

Add `--gpu` flag to the existing `hunt.py` CLI:

```bash
python hunt.py              # Workstation search only (existing behavior, unchanged)
python hunt.py --gpu        # GPU search only
python hunt.py --all        # Both searches in one run
```

`--max-price`, `--show-all`, `--new-only`, `--sandbox`, and `--watch` flags apply to whichever search profile(s) are active.

Default behavior (no flags) must remain unchanged — existing workstation search runs exactly as before. The GPU search is opt-in.

---

## Persistence and Change Detection

Same logic as workstation hunter. Per-run, for GPU results:
1. New listings — not in `cache/gpu_results.json` previously
2. Price drops — lower price than last seen
3. Disappeared — in cache but not returned this run → mark `sold_or_pulled`
4. Flag changes — if a listing previously had no mining flag and now does (or vice versa), surface as a change

Cache entry structure mirrors workstation structure exactly, with these additions:

```json
{
  "item_id": "...",
  "title": "...",
  "price": 0.00,
  "score": 0,
  "card_confirmed": "RTX 3090 24GB",
  "seller_feedback": 99.5,
  "seller_transactions": 312,
  "return_policy": "30-day returns",
  "local_pickup": false,
  "nvlink_included": false,
  "first_seen": "ISO timestamp",
  "last_seen": "ISO timestamp",
  "status": "active|sold_or_pulled",
  "flags": ["MINING_DISCLOSED", "REPASTED", "NVLINK_INCLUDED"]
}
```

---

## Build Order

Add the GPU search as a feature branch on top of the existing working workstation hunter. Do not modify the workstation hunter code — add only.

1. Add `GPU_QUERIES` and GPU-specific filter constants
2. Add GPU discard filter logic (separate function from workstation discard)
3. Add GPU scoring model (separate function from workstation scorer)
4. Add mining flag detection
5. Add GPU persistence using separate cache files
6. Add GPU output section to terminal display
7. Add `--gpu` and `--all` CLI flags
8. Test with `--sandbox --gpu`, confirm separation from workstation results
9. Test with `--all`, confirm both sections appear and cache files remain separate
10. Production run with `--gpu`, show top 5

PR description must include confirmation that running `python hunt.py` (no flags) produces identical output to pre-GPU-feature behavior.

---

## Known Limitations to Document

- Mining history prior to the seller's ownership cannot be detected. A card that was mined and then sold to a non-miner who relists it will show no mining flags. This is an inherent limitation of self-reported listing data.
- Fan condition cannot be assessed from listing text alone. Even with `REPASTED` flag absent, fans on a heavily used 3090 may be worn. Physical inspection or a burn-in test is the only reliable check.
- NVLink bridge detection relies on the seller mentioning it explicitly. Sellers who include it without mentioning it in text will not receive the bonus points. Assume the bridge is absent unless stated.
- The $350 discard floor will exclude damaged/parts listings that could theoretically be repaired. This is intentional — this search is for operational cards, not repair projects.

---

## Timing Gate Note

This search module is for **price discovery and market calibration only** at time of build. The workstation (P620 / 5975WX / 128GB) must be received, tested for GPU slot functionality (PCIe x16 slot, power delivery from 1000W PSU), and confirmed operational before any GPU purchase is initiated.

The hunter should not display any "buy now" urgency language for GPU results. "New listing" and "price drop" flags are informational. The human decides when the timing gate opens.

---

*Spec version 1.0 — May 2026*  
*Companion document: ebay_hunter_spec.md (workstation search)*

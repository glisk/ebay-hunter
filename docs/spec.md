# eBay Workstation Hunter — Build Spec

## Purpose

Build a Python command-line tool that searches eBay for Threadripper PRO 5000-series workstations, scores each listing against a defined criteria model, detects new listings between runs, and alerts on high-priority candidates. eBay's native interface optimizes for promoted listings over relevant ones. This tool inverts that.

---

## Prerequisites

Before building, the user will supply a `.env` file containing:

```
EBAY_CLIENT_ID=your_client_id_here
EBAY_CLIENT_SECRET=your_client_secret_here
EBAY_ENVIRONMENT=production
```

Credentials are obtained from developer.ebay.com. Never hardcode credentials. Never commit `.env` to version control. Add `.env` to `.gitignore` on first run if not already present.

---

## API

**eBay Browse API (Buy APIs).** Not the legacy Finding API.

Base URL (production): `https://api.ebay.com`
Base URL (sandbox): `https://api.sandbox.ebay.com`

**Auth:** OAuth 2.0 client credentials flow. App-level token, no user login required for read-only search.

Token endpoint: `POST /identity/v1/oauth2/token`
- Header: `Authorization: Basic base64(CLIENT_ID:CLIENT_SECRET)`
- Body: `grant_type=client_credentials&scope=https://api.ebay.com/oauth/api_scope`

Cache the token. Refresh only when expired. Store token and expiry in a local `cache/token.json` file.

Search endpoint: `GET /buy/browse/v1/item_summary/search`

Key parameters:
- `q` — search query string
- `filter` — pipe-separated filters (see below)
- `sort` — `newlyListed` for fresh inventory first
- `limit` — 50 per request
- `offset` — for pagination

eBay filter syntax example:
```
filter=conditions:{USED|SELLER_REFURBISHED},price:[0..2000],priceCurrency:USD,itemLocationCountry:US
```

---

## Target Hardware Profile

### Qualifying Platforms
- Lenovo ThinkStation P620
- Dell Precision 7865
- HP Z6 G5 A

### Qualifying CPUs (Threadripper PRO 5000-series, WRX80 platform)
| CPU | Cores | Priority |
|---|---|---|
| 5945WX | 12 | Acceptable |
| 5955WX | 16 | Good |
| 5965WX | 24 | Preferred |
| 5975WX | 32 | Preferred |
| 5995WX | 64 | Filter out unless price anomaly (<$1,200) |

### Automatic Discard Conditions
- Listing mentions 3000-series CPU: 3945WX, 3955WX, 3975WX, 3995WX
- Condition is "For parts/not working"
- Seller is outside the United States
- Seller feedback score below 95% OR fewer than 10 transactions
- Format is Auction with less than 12 hours remaining (unless Buy It Now also available)
- Price above $2,000 (configurable via flag)

---

## Search Query Strategy

Run all queries. Deduplicate results by eBay item ID before scoring. A listing appearing in multiple query results is noted in output but shown only once.

```python
QUERIES = [
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
```

Paginate each query to a maximum of 200 results (4 pages of 50). Stop early if results stop being relevant (heuristic: if fewer than 3 results on a page pass the discard filter, stop paginating that query).

---

## PSU Classification

Parse listing title and description text for PSU mentions:

| Signal | Classification | Score Impact |
|---|---|---|
| "900W", "1000W", "1200W", "1kW" | GREEN — confirmed adequate | Full points |
| "450W" | RED — inadequate for 3090 | Zero PSU points, add warning flag |
| No PSU mention found | YELLOW — unknown, needs follow-up | Partial points |

Store PSU classification in the result object. Display clearly in output.

---

## Scoring Model

Each listing scores 0–100. Listings below 40 are discarded silently. Scores are deterministic given the same listing data.

| Criterion | Max Points | Scoring Logic |
|---|---|---|
| CPU generation confirmed 5000-series | 25 | 25 if confirmed, 0 if 3000-series detected, 10 if unknown/unspecified |
| RAM ≥ 128GB | 20 | 20 if 128GB+, 10 if 64GB, 0 if <64GB or unspecified |
| PSU ≥ 900W confirmed | 20 | 20 if GREEN, 10 if YELLOW, 0 if RED |
| Seller feedback | 10 | 10 if ≥99%, 8 if ≥98%, 6 if ≥97%, 4 if ≥95%, 0 if <95% |
| Price vs. expected range | 10 | See pricing model below |
| No GPU included (not paying for one) | 5 | 5 if no GPU, 2 if GPU included (paying for something not needed), 3 if unspecified |
| Local pickup available | 5 | 5 if local pickup offered, 0 otherwise |
| Storage included | 5 | 5 if any SSD/NVMe mentioned, 0 otherwise |

**Total: 100 points**

Priority tiers:
- **70–100:** PRIORITY — surface immediately, write to `high-priority.json`
- **55–69:** REVIEW — worth manual examination
- **40–54:** MARGINAL — listed but deprioritized
- **<40:** Discarded, not shown

---

## Pricing Model

Used to compute the price score component (0–10 points) and to flag anomalies.

| Configuration | Expected Range | Suspicious Low | Overpriced Above |
|---|---|---|---|
| 5945WX, 64GB | $700–1,000 | <$500 | >$1,100 |
| 5945WX, 128GB | $1,000–1,400 | <$700 | >$1,600 |
| 5955WX, 128GB | $1,100–1,500 | <$800 | >$1,700 |
| 5965WX, 128GB | $1,200–1,800 | <$900 | >$2,000 |
| 5975WX, 128GB | $1,400–2,000 | <$1,100 | >$2,200 |
| Unknown config | $800–1,600 | <$600 | >$2,000 |

Price score logic:
- Within expected range: 10 points
- Up to 15% below low end: 10 points (potential deal)
- Suspicious low (possible scam or parts unit): 5 points + SUSPICIOUS flag
- Up to 15% above high end: 5 points
- Overpriced: 0 points

Suspicious low listings are NOT discarded — they are surfaced with a clear flag. These are the deals. They need manual verification, not automatic dismissal.

---

## Persistence and Change Detection

All results are stored in `cache/results.json` keyed by eBay item ID with timestamp of first seen and last seen.

On each run, after fetching and scoring:

1. **New listings** — item IDs not present in previous results. Flag prominently in output.
2. **Price drops** — listings seen before with lower current price. Show old price and new price.
3. **Disappeared listings** — items in cache not returned in current results. Mark as `sold_or_pulled`. These are useful for calibrating how quickly good deals move.
4. **Unchanged listings** — update `last_seen` timestamp only.

Cache structure per item:
```json
{
  "item_id": "...",
  "title": "...",
  "price": 0.00,
  "score": 0,
  "psu_status": "GREEN|YELLOW|RED",
  "cpu_detected": "5975WX",
  "ram_detected": "128GB",
  "seller_feedback": 99.1,
  "url": "...",
  "location": "...",
  "local_pickup": false,
  "first_seen": "ISO timestamp",
  "last_seen": "ISO timestamp",
  "status": "active|sold_or_pulled",
  "flags": ["SUSPICIOUS_LOW", "NEW", "PRICE_DROP"]
}
```

---

## Output

### Terminal output (every run)

Use the `rich` library for formatted terminal output.

Structure:
1. Run summary: timestamp, queries executed, total results fetched, after dedup, after discard
2. **NEW LISTINGS** section (if any) — shown first, regardless of score
3. **PRIORITY** listings (score 70+)
4. **REVIEW** listings (score 55–69) — compact format
5. **Recently disappeared** listings — last 5, with note "sold or pulled"

Each listing display includes: score, price, CPU, RAM, PSU status (colored GREEN/YELLOW/RED), seller feedback, local pickup indicator, and direct eBay URL.

### File outputs

- `cache/results.json` — full persistent store, updated every run
- `cache/high-priority.json` — only PRIORITY tier listings, current actives
- `cache/run-log.json` — append-only log of each run: timestamp, counts, new listings found

---

## CLI Interface

```
python hunt.py                    # Single run, show results
python hunt.py --watch            # Continuous mode, default 4 hour interval
python hunt.py --watch --interval 60  # Continuous mode, 60 minute interval
python hunt.py --max-price 1500   # Override default $2000 ceiling
python hunt.py --show-all         # Show MARGINAL tier as well
python hunt.py --new-only         # Show only listings not seen before
python hunt.py --sandbox          # Use eBay sandbox environment for testing
```

---

## Stack

- **Python 3.9+**
- `requests` — API calls
- `rich` — terminal formatting
- `python-dotenv` — credential loading
- Standard library only beyond these three: `json`, `os`, `time`, `datetime`, `base64`, `hashlib`

No virtual environment required if dependencies are pip-installed globally. If the user prefers a venv, create one but document the activation command clearly in the README.

---

## Build Order

Build and test incrementally in this sequence. Do not proceed to the next step until the current one works.

1. **Auth only** — load credentials from `.env`, obtain OAuth token, print token type and expiry. Confirm API handshake works before any search logic.

2. **Single query, raw results** — run one hardcoded query, print raw eBay response, confirm result structure matches expected schema.

3. **All queries with dedup** — run full query set, deduplicate by item ID, print count at each stage.

4. **Discard filters** — apply all automatic discard rules, print discard reasons for rejected listings during this phase (useful for tuning).

5. **Scoring model** — apply full scoring, print scored results sorted by score descending.

6. **Persistence and change detection** — load previous cache, compare, flag new/changed/disappeared, write updated cache.

7. **Rich terminal output** — replace print statements with formatted rich output.

8. **CLI arguments** — add argparse for all flags.

9. **Watch mode** — add continuous polling loop with configurable interval.

---

## README Requirements

The tool's README.md must include:
- Setup instructions (pip install, .env file creation)
- How to get eBay developer credentials (link to developer.ebay.com)
- All CLI flags with examples
- What each output file contains
- How scoring works (brief)
- Known limitations

---

## Known Limitations to Document

- eBay listing text is inconsistent. CPU and RAM detection relies on keyword matching in titles and descriptions. Listings with unusual formatting or abbreviations may be misclassified as unknown rather than detected correctly.
- PSU wattage is rarely listed. YELLOW (unknown) will be the most common PSU status.
- Seller feedback percentage requires a separate API call per listing if not included in the search result summary. Implement as a batch enrichment step with rate limiting, or skip if the Browse API includes it in summary results — check the actual API response before deciding.
- eBay's Browse API has daily call limits. Cache aggressively. Do not re-fetch listings seen in the last 2 hours unless `--force` flag is passed.

---

*Spec version 1.0 — May 2026*

---

## Appendix: Production Verification Notes (2026-05-03)

### Seller feedback in Browse API summary responses
`seller.feedbackPercentage` and `seller.feedbackScore` are both present in
itemSummary objects. No per-item enrichment call is needed.

### Platform-specific query effectiveness
Compound platform+CPU queries ("ThinkStation P620 Threadripper PRO 5000",
"Precision 7865 Threadripper PRO", "HP Z6 G5 Threadripper 5000") return zero
results with the full filter set applied. CPU-specific queries ("5975WX
workstation", "5945WX workstation", etc.) are the effective discovery vectors.
Platform queries are retained in case search index changes, but should not be
relied upon for coverage.

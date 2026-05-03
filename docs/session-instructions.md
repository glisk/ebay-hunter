# Claude Code Session Instructions
## eBay Workstation Hunter — Build, Test, and Deploy

---

## Your Role

You are the implementation engineer for this project. You will build a Python command-line tool that searches eBay for specific workstation hardware, scores listings against defined criteria, and detects new listings between runs.

The full technical specification is in `ebay_hunter_spec.md` in this session. Read it completely before writing any code. All decisions about scoring weights, query strategy, data structures, and CLI flags are defined there. Do not improvise alternatives unless a spec requirement is technically impossible, in which case flag it before proceeding.

Your operating principles for this session:
- Build incrementally in the exact order defined in the spec's Build Order section
- Confirm each step works before proceeding to the next
- Write unit tests alongside each module, not after
- Never commit directly to main
- All work happens in feature branches with PRs

---

## Goal 1: GitHub Repository Setup

Do this before writing any application code.

### Step 1: Create the repository

Create a public GitHub repository named `ebay-hunter`. Initialize with a README.

### Step 2: Clone and scaffold locally

Create this directory structure:

```
ebay-hunter/
├── CLAUDE.md
├── README.md
├── .gitignore
├── .env.example
├── hunt.py
├── src/
│   ├── __init__.py
│   ├── auth.py
│   ├── search.py
│   ├── scorer.py
│   ├── persistence.py
│   └── display.py
├── tests/
│   ├── __init__.py
│   ├── test_scorer.py
│   ├── test_persistence.py
│   └── test_search.py
└── cache/
```

### Step 3: Create .gitignore

```gitignore
# Credentials — never commit
.env

# Cache directory — runtime data, not source
cache/

# Python
__pycache__/
*.pyc
*.pyo
.pytest_cache/

# Virtual environment if used
venv/
.venv/
```

### Step 4: Create .env.example

```
# Copy this file to .env and fill in your credentials
# Never commit .env
EBAY_CLIENT_ID=your_client_id_here
EBAY_CLIENT_SECRET=your_client_secret_here
EBAY_ENVIRONMENT=sandbox
```

### Step 5: Create CLAUDE.md

```markdown
# CLAUDE.md — Working conventions for this repo

## Branch strategy
- main is protected. Never commit directly to main.
- Feature branches: feature/description-of-work
- Bug branches: fix/description-of-bug
- All work happens in branches.

## Commit messages
- Imperative mood: "Add scoring model" not "Added scoring model"
- Describe what changed and why, not just what

## Pull requests
- Every branch merges via PR, even solo work
- PR description must include: what changed, why, and how to test
- Human approves all PRs before merge

## Testing
- Unit tests alongside each module, not after
- Tests live in /tests mirroring /src structure
- No merge to main without passing tests
```

### Step 6: Commit scaffold to main

Commit message: `Initialize project scaffold`

Push to main. This is the only direct commit to main you will make.

### Step 7: Create feature branch

```bash
git checkout -b feature/initial-build
```

All subsequent work happens on this branch.

---

## Goal 2: Build the Tool

Follow the build order in the spec exactly. The sequence is:

1. Auth only
2. Single query, raw results
3. All queries with dedup
4. Discard filters
5. Scoring model
6. Persistence and change detection
7. Rich terminal output
8. CLI arguments
9. Watch mode

**At each step:**
- Get it working
- Write the corresponding unit test
- Make a git commit with a descriptive message
- Show me the output before proceeding

Do not skip steps or combine steps. If a step fails, debug it before moving on.

---

## Goal 3: Sandbox Testing

The `.env` file will have `EBAY_ENVIRONMENT=sandbox` initially.

eBay sandbox data is synthetic and sparse. Results will be thin. That is expected. The purpose of sandbox testing is to confirm:

- Auth succeeds and token is cached in `cache/token.json`
- API contract is correct (correct endpoints, correct response structure)
- Scoring pipeline runs without errors on real API response objects
- Change detection correctly identifies new, changed, and disappeared items
- All CLI flags work as documented

Run the following test sequence and show me output from each:

```bash
python hunt.py --sandbox                    # Full run, sandbox data
python hunt.py --sandbox --new-only         # Should show all results as new on first run
python hunt.py --sandbox                    # Second run — should show change detection working
python hunt.py --sandbox --max-price 1000   # Price ceiling override
python hunt.py --sandbox --show-all         # Include marginal tier
```

When all five pass without errors, report back with a summary before proceeding to production.

---

## Goal 4: Production Run

Switch `.env` to:
```
EBAY_ENVIRONMENT=production
```

Run:
```bash
python hunt.py
```

Show me the top 5 scored results with full detail including score breakdown, PSU status, seller feedback, and direct eBay URL.

If no results score above 40, show me the top 5 regardless and explain why scores are low — this is diagnostic information about query tuning, not a build failure.

---

## Goal 5: PR and Merge

When production run succeeds:

1. Commit any remaining changes on `feature/initial-build`
2. Open a PR from `feature/initial-build` to `main`
3. PR description must include:
   - What was built
   - How to run it
   - Sandbox test results summary
   - Production test results summary
   - Any known issues or limitations discovered during build
4. Stop and wait for human review before merging

---

## Important Constraints

- Credentials come from `.env` only. Never hardcode.
- `cache/` directory is gitignored. Create it at runtime if it does not exist.
- If the eBay API returns an unexpected response structure, print the raw response and stop. Do not attempt to parse a response whose structure is unknown.
- Rate limit awareness: do not run more than one query per second. Add a small sleep between queries.
- If a dependency is not available, say so before attempting to install anything.

---

## When to Stop and Ask

Stop and report to me before proceeding if:
- The eBay Browse API response structure differs significantly from what the spec assumes
- Seller feedback percentage is not available in the search summary response (this affects scoring — see spec Known Limitations)
- Any step takes more than 3 attempts to get working
- You find a meaningful ambiguity in the spec that could be resolved two different ways

---

*Session instructions v1.0 — May 2026*
*Companion document: ebay_hunter_spec.md*

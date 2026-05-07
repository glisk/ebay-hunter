#!/usr/bin/env python3
"""
eBay Workstation Hunter — main entry point.

Usage:
  python hunt.py                     Single run
  python hunt.py --watch             Continuous mode (default 4h interval)
  python hunt.py --watch --interval 60  Continuous mode, 60 minute interval
  python hunt.py --max-price 1500    Override $2,000 price ceiling
  python hunt.py --show-all          Include MARGINAL tier in output
  python hunt.py --new-only          Show only listings not seen before
  python hunt.py --sandbox           Use eBay sandbox environment
  python hunt.py --force-refresh     Force OAuth token refresh
  python hunt.py --verbose-filters   Print discard reasons to stdout
  python hunt.py --report            Write cache/report.md for review in Claude.ai
"""

import argparse
import sys
import time

# Suppress SSL warnings for verify=False (expected on this machine)
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hunt.py",
        description=(
            "Search eBay for Threadripper PRO 5000-series workstations, "
            "score listings, and surface high-priority candidates."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Run continuously on a timer (default 4 hour interval).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=240,
        metavar="MINUTES",
        help="Polling interval in minutes for watch mode (default: 240).",
    )
    parser.add_argument(
        "--max-price",
        type=float,
        default=2000.0,
        metavar="USD",
        help="Price ceiling in USD — listings above this are discarded (default: 2000).",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Include MARGINAL tier listings (score 40–54) in output.",
    )
    parser.add_argument(
        "--new-only",
        action="store_true",
        help="Show only listings not seen in a previous run.",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Use eBay sandbox API environment (for testing).",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Force OAuth token refresh, bypassing cache.",
    )
    parser.add_argument(
        "--verbose-filters",
        action="store_true",
        help="Print discard reasons for each filtered-out listing.",
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Write a plain markdown summary to cache/report.md (for pasting into Claude.ai).",
    )
    return parser


def run_once(args: argparse.Namespace) -> bool:
    """
    Execute a single hunt cycle.

    Returns True on success, False on error.
    """
    from src import auth, search, filters, scorer, persistence, display, database
    from datetime import datetime, timezone

    try:
        # 1. Fetch all results from eBay
        raw_items, query_hits = search.run_all_queries(
            sandbox=args.sandbox,
            max_price=args.max_price,
            force_refresh=args.force_refresh,
        )
        total_fetched = len(raw_items)
        after_dedup = total_fetched  # run_all_queries already deduplicates

        # 2. Apply discard filters
        kept, discarded = filters.filter_items(
            raw_items,
            max_price=args.max_price,
            verbose=args.verbose_filters,
        )
        after_discard = len(kept)

        # 3. Score remaining items
        scored = scorer.score_items(kept)
        after_score = len(scored)

        # 4. Load previous cache and detect changes
        store = persistence.load_cache()
        updated_store, new_listings, price_drops, disappeared = persistence.merge_run(scored, store)

        # 5. Save updated state
        persistence.save_results(updated_store)
        persistence.save_high_priority(updated_store)
        persistence.append_run_log(
            total_fetched=total_fetched,
            after_dedup=after_dedup,
            after_discard=after_discard,
            after_score=after_score,
            new_count=len(new_listings),
            price_drop_count=len(price_drops),
            disappeared_count=len(disappeared),
            queries_run=search.QUERIES,
        )

        # 6. Record price observations in SQLite history DB
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = database.open_db()
        obs_excluded = 0
        for item in scored:
            item_id = item.get("item_id", "")
            queries = query_hits.get(item_id, [])
            search_query = queries[0] if queries else "unknown"
            recorded = database.record_observation(
                conn=conn,
                item_id=item_id,
                search_query=search_query,
                observed_at=observed_at,
                price=item.get("price", 0.0),
                score=item.get("score"),
                flags=item.get("flags", []),
            )
            if not recorded:
                obs_excluded += 1
        for item in disappeared:
            item_id = item.get("item_id", "")
            queries = query_hits.get(item_id, [])
            search_query = queries[0] if queries else "unknown"
            database.mark_disappeared(
                conn=conn,
                item_id=item_id,
                observed_at=observed_at,
                search_query=search_query,
                price=item.get("price", 0.0),
            )
        conn.commit()
        history_depth = database.history_depth_days(conn)
        conn.close()

        # 7. Render output
        display.print_full_results(
            scored_items=scored,
            new_listings=new_listings,
            price_drops=price_drops,
            disappeared=disappeared,
            total_fetched=total_fetched,
            after_dedup=after_dedup,
            after_discard=after_discard,
            show_marginal=args.show_all,
            new_only=args.new_only,
        )

        # 8. Write markdown report if requested
        if args.report:
            from src import report as reporter
            path = reporter.write_report(
                scored_items=scored,
                new_listings=new_listings,
                price_drops=price_drops,
                disappeared=disappeared,
                total_fetched=total_fetched,
                after_dedup=after_dedup,
                after_discard=after_discard,
                history_depth=history_depth,
                obs_excluded=obs_excluded,
            )
            display.console.print(f"[dim]Report written to {path}[/dim]")

        return True

    except EnvironmentError as exc:
        from src import display
        display.print_error(str(exc))
        return False
    except Exception as exc:  # pylint: disable=broad-except
        from src import display
        display.print_error(f"Unexpected error: {exc}")
        if args.verbose_filters:
            import traceback
            traceback.print_exc()
        return False


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if not args.watch:
        success = run_once(args)
        sys.exit(0 if success else 1)

    # Watch mode
    run_number = 0
    interval_seconds = args.interval * 60

    from src import display as out

    while True:
        run_number += 1
        if run_number > 1:
            out.print_watch_header(args.interval, run_number)

        run_once(args)

        # After first run, force_refresh can be False (token cached)
        args.force_refresh = False

        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            out.console.print("\n[dim]Watch mode stopped.[/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
eBay GPU Hunter — RTX 3090 market intelligence.

Separate program from hunt.py (workstation hunter). Shares auth layer
and SQLite DB (separate table), but all cache files and reports are independent.

Usage:
  python gpu_hunt.py                     Single run
  python gpu_hunt.py --watch             Continuous mode (default 4h interval)
  python gpu_hunt.py --watch --interval 60
  python gpu_hunt.py --max-price 900     Override $1,000 price ceiling
  python gpu_hunt.py --show-all          Include MARGINAL tier in output
  python gpu_hunt.py --new-only          Show only listings not seen before
  python gpu_hunt.py --sandbox           Use eBay sandbox environment
  python gpu_hunt.py --force-refresh     Force OAuth token refresh
  python gpu_hunt.py --verbose-filters   Print discard reasons to stdout
  python gpu_hunt.py --report            Write cache/gpu-report.md
"""

import argparse
import sys
import time

import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gpu_hunt.py",
        description=(
            "Search eBay for RTX 3090 24GB GPUs and surface market intelligence. "
            "Purchase decision is gated on workstation confirmation — see spec."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--watch", action="store_true",
                        help="Run continuously on a timer (default 4 hour interval).")
    parser.add_argument("--interval", type=int, default=240, metavar="MINUTES",
                        help="Polling interval in minutes for watch mode (default: 240).")
    parser.add_argument("--max-price", type=float, default=1000.0, metavar="USD",
                        help="Price ceiling in USD (default: 1000).")
    parser.add_argument("--show-all", action="store_true",
                        help="Include MARGINAL tier listings (score 40–54) in output.")
    parser.add_argument("--new-only", action="store_true",
                        help="Show only listings not seen in a previous run.")
    parser.add_argument("--sandbox", action="store_true",
                        help="Use eBay sandbox API environment.")
    parser.add_argument("--force-refresh", action="store_true",
                        help="Force OAuth token refresh, bypassing cache.")
    parser.add_argument("--verbose-filters", action="store_true",
                        help="Print discard reasons for each filtered-out listing.")
    parser.add_argument("--report", action="store_true",
                        help="Write a plain markdown summary to cache/gpu-report.md.")
    return parser


def run_once(args: argparse.Namespace) -> bool:
    from src import gpu_search, gpu_filters, gpu_scorer, gpu_persistence, gpu_display, database
    from datetime import datetime, timezone

    try:
        # 1. Fetch GPU listings from eBay
        raw_items, query_hits = gpu_search.run_gpu_queries(
            sandbox=args.sandbox,
            max_price=args.max_price,
            force_refresh=args.force_refresh,
        )
        total_fetched = len(raw_items)
        after_dedup = total_fetched

        # 2. Load cache early — needed for description re-use in enrichment
        store = gpu_persistence.load_gpu_cache()

        # 3. Title-based discard filters
        kept, discarded = gpu_filters.filter_gpu_items(
            raw_items,
            max_price=args.max_price,
            verbose=args.verbose_filters,
        )

        # 4. Enrich survivors with full description text (1 API call/item, cached)
        kept = gpu_search.enrich_gpu_items(
            kept,
            store=store,
            sandbox=args.sandbox,
        )

        # 5. Description-based discard (functional defects disclosed in body text)
        kept, desc_discarded = gpu_filters.filter_by_description(
            kept,
            verbose=args.verbose_filters,
        )
        discarded.extend(desc_discarded)
        after_discard = len(kept)

        # 6. Score remaining items
        scored = gpu_scorer.score_gpu_items(kept)
        after_score = len(scored)

        # 7. Detect changes against cache (already loaded in step 2)
        updated_store, new_listings, price_drops, disappeared = gpu_persistence.merge_gpu_run(scored, store)

        # 8. Save updated GPU state
        gpu_persistence.save_gpu_results(updated_store)
        gpu_persistence.save_gpu_high_priority(updated_store)
        gpu_persistence.append_gpu_run_log(
            total_fetched=total_fetched,
            after_dedup=after_dedup,
            after_discard=after_discard,
            after_score=after_score,
            new_count=len(new_listings),
            price_drop_count=len(price_drops),
            disappeared_count=len(disappeared),
            queries_run=gpu_search.GPU_QUERIES,
        )

        # 9. Record GPU price observations in SQLite (gpu_price_observations table)
        observed_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        conn = database.open_db()
        obs_excluded = 0
        for item in scored:
            item_id = item.get("item_id", "")
            queries = query_hits.get(item_id, [])
            search_query = queries[0] if queries else "unknown"
            recorded = database.record_gpu_observation(
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
            database.mark_gpu_disappeared(
                conn=conn,
                item_id=item_id,
                observed_at=observed_at,
                search_query=search_query,
                price=item.get("price", 0.0),
            )
        conn.commit()
        history_depth = database.gpu_history_depth_days(conn)
        conn.close()

        # 10. Render terminal output
        gpu_display.print_gpu_full_results(
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

        # 11. Write markdown report if requested
        if args.report:
            from src import gpu_report as reporter
            discard_breakdown = gpu_filters.categorize_discard_reasons(discarded)
            path = reporter.write_gpu_report(
                scored_items=scored,
                new_listings=new_listings,
                price_drops=price_drops,
                disappeared=disappeared,
                total_fetched=total_fetched,
                after_dedup=after_dedup,
                after_discard=after_discard,
                history_depth=history_depth,
                obs_excluded=obs_excluded,
                discard_breakdown=discard_breakdown,
            )
            gpu_display.console.print(f"[dim]GPU report written to {path}[/dim]")

        return True

    except EnvironmentError as exc:
        from src import gpu_display as out
        out.console.print(f"[bold red]{exc}[/bold red]")
        return False
    except Exception as exc:  # pylint: disable=broad-except
        from src import gpu_display as out
        out.console.print(f"[bold red]Unexpected error: {exc}[/bold red]")
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

    run_number = 0
    interval_seconds = args.interval * 60

    from src import gpu_display as out

    while True:
        run_number += 1
        if run_number > 1:
            out.console.print()
            from rich.rule import Rule
            out.console.print(Rule(
                f"[bold cyan]GPU Watch — run #{run_number} — next in {args.interval}m[/bold cyan]",
                style="cyan",
            ))

        run_once(args)
        args.force_refresh = False

        try:
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            out.console.print("\n[dim]GPU watch mode stopped.[/dim]")
            sys.exit(0)


if __name__ == "__main__":
    main()

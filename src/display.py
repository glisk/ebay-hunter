"""
Rich terminal output formatting for eBay Hunter results.

Renders run summaries, new listings, priority/review tiers,
and recently disappeared items.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from rich.text import Text
from rich.rule import Rule
from rich.padding import Padding

console = Console()

# PSU status colors
PSU_COLORS = {
    "GREEN": "bold green",
    "YELLOW": "bold yellow",
    "RED": "bold red",
}

# Tier colors
TIER_COLORS = {
    "PRIORITY": "bold white on red",
    "REVIEW": "bold yellow",
    "MARGINAL": "dim",
    "DISCARD": "dim",
}

# Score bar characters
SCORE_BAR_WIDTH = 20


def _score_bar(score: int) -> str:
    """Visual score bar: ██████░░░░░░░░ 73"""
    filled = int(SCORE_BAR_WIDTH * score / 100)
    empty = SCORE_BAR_WIDTH - filled
    return f"{'█' * filled}{'░' * empty} {score}"


def _psu_badge(psu_status: str) -> Text:
    text = Text(psu_status, style=PSU_COLORS.get(psu_status, ""))
    return text


def _tier_badge(tier: str) -> Text:
    return Text(f" {tier} ", style=TIER_COLORS.get(tier, ""))


def _flag_badges(flags: list[str]) -> Text:
    if not flags:
        return Text("")
    result = Text()
    badge_styles = {
        "NEW": ("NEW", "bold green on dark_green"),
        "PRICE_DROP": ("↓ PRICE DROP", "bold cyan"),
        "SUSPICIOUS_LOW": ("⚠ SUSPICIOUS LOW", "bold yellow on dark_orange3"),
        "5995WX_ANOMALY": ("5995WX ANOMALY", "bold magenta"),
    }
    for flag in flags:
        style_pair = badge_styles.get(flag, (flag, "dim"))
        if len(result) > 0:
            result.append("  ")
        result.append(f"[{style_pair[0]}]", style=style_pair[1])
    return result


def _format_price(price: float) -> str:
    if price <= 0:
        return "?"
    return f"${price:,.0f}"


def _short_url(url: str) -> str:
    """Trim eBay URL to just the item ID path for display."""
    if "/itm/" in url:
        parts = url.split("/itm/")
        if len(parts) > 1:
            item_id = parts[1].split("?")[0].split("/")[0]
            return f"ebay.com/itm/{item_id}"
    return url[:60] + "..." if len(url) > 60 else url


def _time_ago(iso_str: str) -> str:
    """Return a human-friendly 'N hours ago' string from an ISO timestamp."""
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            mins = int(diff.total_seconds() / 60)
            return f"{mins}m ago"
        if hours < 48:
            return f"{hours}h ago"
        days = hours // 24
        return f"{days}d ago"
    except ValueError:
        return ""


# ---------------------------------------------------------------------------
# Run summary
# ---------------------------------------------------------------------------

def print_run_summary(
    timestamp: str,
    queries_run: int,
    total_fetched: int,
    after_dedup: int,
    after_discard: int,
    after_score: int,
) -> None:
    """Print the run header summary."""
    console.print()
    console.print(Rule(f"[bold cyan]eBay Hunter[/bold cyan] — {timestamp}", style="cyan"))
    console.print()

    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(style="bold")

    table.add_row("Queries run", str(queries_run))
    table.add_row("Total fetched", str(total_fetched))
    table.add_row("After dedup", str(after_dedup))
    table.add_row("After discard filters", str(after_discard))
    table.add_row("After score threshold", str(after_score))

    console.print(Padding(table, (0, 2)))
    console.print()


# ---------------------------------------------------------------------------
# Item cards
# ---------------------------------------------------------------------------

def _item_card(item: dict[str, Any], compact: bool = False) -> Panel:
    """Render a single item as a rich Panel."""
    score = item.get("score", 0)
    tier = item.get("tier", "")
    flags = item.get("flags", [])
    title = item.get("title", "No title")
    price = item.get("price", 0.0)
    cpu = item.get("cpu_detected") or "CPU unknown"
    ram = item.get("ram_detected") or "RAM unknown"
    psu = item.get("psu_status", "YELLOW")
    feedback = item.get("seller_feedback")
    local = item.get("local_pickup", False)
    location = item.get("location", "")
    url = item.get("url", "")
    first_seen = item.get("first_seen", "")
    old_price = item.get("old_price")

    # Build title line
    title_text = Text()
    title_text.append(f"{title[:80]}", style="bold white")

    # Score bar
    score_color = "green" if score >= 70 else "yellow" if score >= 55 else "dim"
    score_text = Text(_score_bar(score), style=score_color)

    # Flags
    flag_text = _flag_badges(flags)

    # Price
    price_text = Text(_format_price(price), style="bold green")
    if old_price and old_price > price:
        price_text.append(f"  was {_format_price(old_price)}", style="dim red strike")

    # PSU badge
    psu_text = _psu_badge(psu)
    if psu == "RED":
        psu_text.append(" ⚠ 450W inadequate for GPU", style="bold red")

    # Feedback
    if feedback is not None:
        fb_style = "green" if feedback >= 99 else "yellow" if feedback >= 95 else "red"
        feedback_str = f"{feedback:.1f}%"
        feedback_text = Text(feedback_str, style=fb_style)
    else:
        feedback_text = Text("unknown", style="dim")

    # Local pickup
    pickup_text = Text("Yes", style="green") if local else Text("No", style="dim")

    if compact:
        # Single-line compact format for REVIEW tier
        line = Text()
        line.append(f"[{score:3d}] ", style=score_color)
        line.append(_tier_badge(tier))
        line.append(f"  {_format_price(price):>6}  ", style="bold green")
        line.append(f"{cpu}  {ram}  PSU:", style="")
        line.append(psu, style=PSU_COLORS.get(psu, ""))
        line.append(f"  {title[:55]}", style="dim")
        if flag_text:
            line.append("  ")
            line.append_text(flag_text)
        return line  # type: ignore[return-value]

    # Full card body
    body = Table(box=None, show_header=False, padding=(0, 1))
    body.add_column(style="dim", width=18)
    body.add_column()

    body.add_row("Score", score_text)
    if flag_text:
        body.add_row("", flag_text)
    body.add_row("Price", price_text)
    body.add_row("CPU", Text(cpu, style="bold cyan"))
    body.add_row("RAM", Text(ram, style="cyan"))
    body.add_row("PSU", psu_text)
    body.add_row("Seller feedback", feedback_text)
    body.add_row("Local pickup", pickup_text)
    if location:
        body.add_row("Location", Text(location, style="dim"))
    if first_seen:
        body.add_row("First seen", Text(_time_ago(first_seen), style="dim"))
    body.add_row("URL", Text(_short_url(url), style="link " + url if url else "dim"))

    # Score breakdown (collapsed)
    breakdown = item.get("score_breakdown", {})
    if breakdown:
        bd_parts = "  ".join(f"{k}: {v}" for k, v in breakdown.items())
        body.add_row("Breakdown", Text(bd_parts, style="dim"))

    border_color = "red" if tier == "PRIORITY" else "yellow" if tier == "REVIEW" else "dim"
    return Panel(
        body,
        title=title_text,
        border_style=border_color,
        padding=(0, 1),
    )


# ---------------------------------------------------------------------------
# Section printers
# ---------------------------------------------------------------------------

def print_new_listings(new_listings: list[dict[str, Any]]) -> None:
    """Print the NEW LISTINGS section."""
    if not new_listings:
        return
    console.print(Rule(f"[bold green] NEW LISTINGS ({len(new_listings)}) [/bold green]", style="green"))
    console.print()
    for item in new_listings:
        console.print(_item_card(item))
        console.print()


def print_priority_listings(items: list[dict[str, Any]]) -> None:
    """Print PRIORITY tier listings (score 70+)."""
    priority = [i for i in items if i.get("tier") == "PRIORITY"]
    if not priority:
        return
    console.print(Rule(f"[bold red] PRIORITY ({len(priority)}) [/bold red]", style="red"))
    console.print()
    for item in priority:
        console.print(_item_card(item))
        console.print()


def print_review_listings(items: list[dict[str, Any]]) -> None:
    """Print REVIEW tier listings (score 55–69) in compact format."""
    review = [i for i in items if i.get("tier") == "REVIEW"]
    if not review:
        return
    console.print(Rule(f"[bold yellow] REVIEW ({len(review)}) [/bold yellow]", style="yellow"))
    console.print()
    for item in review:
        line = _item_card(item, compact=True)
        console.print(Padding(line, (0, 2)))
    console.print()


def print_marginal_listings(items: list[dict[str, Any]]) -> None:
    """Print MARGINAL tier listings (score 40–54) — only shown with --show-all."""
    marginal = [i for i in items if i.get("tier") == "MARGINAL"]
    if not marginal:
        return
    console.print(Rule(f"[dim] MARGINAL ({len(marginal)}) [/dim]", style="dim"))
    console.print()
    for item in marginal:
        line = _item_card(item, compact=True)
        console.print(Padding(line, (0, 2)))
    console.print()


def print_disappeared(disappeared: list[dict[str, Any]], limit: int = 5) -> None:
    """Print recently disappeared (sold or pulled) listings."""
    if not disappeared:
        return
    recent = sorted(
        disappeared,
        key=lambda x: x.get("last_seen", ""),
        reverse=True,
    )[:limit]

    console.print(Rule("[dim] RECENTLY DISAPPEARED [/dim]", style="dim"))
    console.print()

    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="dim")
    table.add_column("Title", max_width=50)
    table.add_column("Price", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Last seen", justify="right")
    table.add_column("Status")

    for item in recent:
        table.add_row(
            item.get("title", "")[:48],
            _format_price(item.get("price", 0)),
            str(item.get("score", 0)),
            _time_ago(item.get("last_seen", "")),
            Text("sold or pulled", style="dim italic"),
        )

    console.print(Padding(table, (0, 2)))
    console.print()


def print_full_results(
    scored_items: list[dict[str, Any]],
    new_listings: list[dict[str, Any]],
    price_drops: list[dict[str, Any]],
    disappeared: list[dict[str, Any]],
    total_fetched: int,
    after_dedup: int,
    after_discard: int,
    show_marginal: bool = False,
    new_only: bool = False,
) -> None:
    """
    Render the full terminal output for a run.

    This is the top-level function called by hunt.py.
    """
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    from .search import QUERIES
    after_score = len(scored_items)

    print_run_summary(
        timestamp=now_str,
        queries_run=len(QUERIES),
        total_fetched=total_fetched,
        after_dedup=after_dedup,
        after_discard=after_discard,
        after_score=after_score,
    )

    if new_only:
        if new_listings:
            print_new_listings(new_listings)
        else:
            console.print("[dim]No new listings found this run.[/dim]")
            console.print()
        return

    # NEW section always comes first
    if new_listings:
        print_new_listings(new_listings)

    # PRIORITY
    print_priority_listings(scored_items)

    # REVIEW
    print_review_listings(scored_items)

    # MARGINAL (opt-in)
    if show_marginal:
        print_marginal_listings(scored_items)

    # DISAPPEARED
    if disappeared:
        print_disappeared(disappeared)

    # Price drops summary (not a separate section — shown inline via flags)
    if price_drops and not any(
        "PRICE_DROP" in i.get("flags", []) for i in scored_items
    ):
        # Price drops that fell below score threshold
        console.print(f"[dim]{len(price_drops)} price drop(s) on sub-threshold listings.[/dim]")

    if not scored_items and not new_listings:
        console.print(Panel(
            "[dim]No listings met the minimum score threshold this run.[/dim]",
            border_style="dim",
        ))
        console.print()


def print_watch_header(interval_minutes: int, run_number: int) -> None:
    """Print the watch-mode run header."""
    console.print()
    console.print(Rule(
        f"[bold cyan]Watch mode — run #{run_number} — next in {interval_minutes}m[/bold cyan]",
        style="cyan",
    ))


def print_error(message: str) -> None:
    """Print a prominent error message."""
    console.print(Panel(f"[bold red]{message}[/bold red]", border_style="red"))

"""
Rich terminal output — RTX 3090 GPU hunter results.

Rendered below workstation results (or standalone when gpu_hunt.py is invoked).
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

TIER_COLORS = {
    "PRIORITY": "bold white on red",
    "REVIEW":   "bold yellow",
    "MARGINAL": "dim",
    "DISCARD":  "dim",
}

SCORE_BAR_WIDTH = 20

GPU_FLAG_STYLES: dict[str, tuple[str, str]] = {
    "NEW":                 ("NEW", "bold green on dark_green"),
    "PRICE_DROP":          ("↓ PRICE DROP", "bold cyan"),
    "SUSPICIOUS_LOW":      ("⚠ SUSPICIOUS LOW", "bold yellow on dark_orange3"),
    "MINING_DISCLOSED":    ("⛏ MINING", "bold yellow"),
    "BIOS_MODIFIED":       ("⚠ BIOS MODIFIED", "bold red"),
    "REPASTED":            ("REPASTED", "dim cyan"),
    "NVLINK_INCLUDED":     ("🔗 NVLINK", "bold green"),
    "TITLE_INCONSISTENCY": ("⚠ TITLE MISMATCH", "bold magenta"),
    "NO_ACTUAL_PHOTO":     ("📷 STOCK PHOTO", "dim yellow"),
    "REPAIR_DISCLOSED":    ("🔧 REPAIR DISCLOSED", "bold red"),
    "SEE_DESCRIPTION":     ("👁 SEE DESCRIPTION", "bold yellow"),
    "FLAG_CHANGED":        ("FLAG CHANGED", "bold white on blue"),
}

CONDITION_LABELS = {
    "tested_photos": "Tested + working (actual photos)",
    "tested":        "Tested + working",
    "refurbished":   "Seller refurbished",
    "used":          "Used",
    "as_is":         "As-is / untested",
}


def _score_bar(score: int) -> str:
    filled = int(SCORE_BAR_WIDTH * score / 100)
    empty = SCORE_BAR_WIDTH - filled
    return f"{'█' * filled}{'░' * empty} {score}"


def _format_price(price: float) -> str:
    return f"${price:,.0f}" if price > 0 else "?"


def _short_url(url: str) -> str:
    if "/itm/" in url:
        parts = url.split("/itm/")
        if len(parts) > 1:
            item_id = parts[1].split("?")[0].split("/")[0]
            return f"ebay.com/itm/{item_id}"
    return url[:60] + "..." if len(url) > 60 else url


def _time_ago(iso_str: str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = datetime.now(timezone.utc) - dt
        hours = int(diff.total_seconds() / 3600)
        if hours < 1:
            return f"{int(diff.total_seconds() / 60)}m ago"
        if hours < 48:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"
    except ValueError:
        return ""


def _flag_badges(flags: list[str]) -> Text:
    if not flags:
        return Text("")
    result = Text()
    for flag in flags:
        style_pair = GPU_FLAG_STYLES.get(flag, (flag, "dim"))
        if len(result) > 0:
            result.append("  ")
        result.append(f"[{style_pair[0]}]", style=style_pair[1])
    return result


def _gpu_item_card(item: dict[str, Any], compact: bool = False) -> Panel | Text:
    score = item.get("score", 0)
    tier = item.get("tier", "")
    flags = item.get("flags", [])
    title = item.get("title", "No title")
    price = item.get("price", 0.0)
    old_price = item.get("old_price")
    card_confirmed = item.get("card_confirmed", "ambiguous")
    condition_tier = item.get("condition_tier", "used")
    nvlink = item.get("nvlink_included", False)
    return_policy = item.get("return_policy", "No returns")
    feedback = item.get("seller_feedback") if item.get("seller_feedback") is not None else item.get("seller_feedback_pct")
    transactions = item.get("seller_transactions") if item.get("seller_transactions") is not None else item.get("seller_feedback_score")
    local = item.get("local_pickup", False)
    url = item.get("url", "")
    first_seen = item.get("first_seen", "")

    score_color = "green" if score >= 70 else "yellow" if score >= 55 else "dim"
    score_text = Text(_score_bar(score), style=score_color)
    flag_text = _flag_badges(flags)

    price_text = Text(_format_price(price), style="bold green")
    if old_price and old_price > price:
        price_text.append(f"  was {_format_price(old_price)}", style="dim red strike")

    card_label = {
        "confirmed": Text("RTX 3090 24GB ✓", style="bold cyan"),
        "ambiguous": Text("RTX 3090 (24GB unconfirmed)", style="yellow"),
        "wrong":     Text("Wrong card detected", style="bold red"),
    }.get(card_confirmed, Text(card_confirmed))

    fb_str = f"{feedback:.1f}%" if feedback is not None else "unknown"
    tx_str = f"  ({transactions:,} transactions)" if transactions else ""
    fb_style = "green" if (feedback or 0) >= 99.5 else "yellow" if (feedback or 0) >= 99.0 else "red"
    feedback_text = Text(f"{fb_str}{tx_str}", style=fb_style if feedback is not None else "dim")

    returns_style = "green" if "30" in return_policy else "yellow" if "14" in return_policy else "dim"

    if compact:
        line = Text()
        line.append(f"[{score:3d}] ", style=score_color)
        line.append(f" {tier} ", style=TIER_COLORS.get(tier, ""))
        line.append(f"  {_format_price(price):>6}  ", style="bold green")
        line.append(f"{'NVLink ' if nvlink else ''}", style="bold green")
        line.append(return_policy, style=returns_style)
        line.append(f"  {title[:50]}", style="dim")
        if flag_text:
            line.append("  ")
            line.append_text(flag_text)
        return line  # type: ignore[return-value]

    body = Table(box=None, show_header=False, padding=(0, 1))
    body.add_column(style="dim", width=20)
    body.add_column()

    body.add_row("Score", score_text)
    if flag_text:
        body.add_row("", flag_text)
    body.add_row("Price", price_text)
    body.add_row("Card", card_label)
    body.add_row("Condition", Text(CONDITION_LABELS.get(condition_tier, condition_tier), style="cyan"))
    body.add_row("NVLink bridge", Text("Included ✓", style="bold green") if nvlink else Text("Not mentioned", style="dim"))
    body.add_row("Return policy", Text(return_policy, style=returns_style))
    body.add_row("Seller feedback", feedback_text)
    body.add_row("Local pickup", Text("Yes", style="green") if local else Text("No", style="dim"))
    if first_seen:
        body.add_row("First seen", Text(_time_ago(first_seen), style="dim"))
    body.add_row("URL", Text(_short_url(url), style="link " + url if url else "dim"))

    breakdown = item.get("score_breakdown", {})
    if breakdown:
        bd_parts = "  ".join(f"{k}: {v}" for k, v in breakdown.items())
        body.add_row("Breakdown", Text(bd_parts, style="dim"))

    border_color = "red" if tier == "PRIORITY" else "yellow" if tier == "REVIEW" else "dim"
    return Panel(
        body,
        title=Text(title[:80], style="bold white"),
        border_style=border_color,
        padding=(0, 1),
    )


# ---------------------------------------------------------------------------
# Section printers
# ---------------------------------------------------------------------------

def print_gpu_header(total_fetched: int, after_discard: int, after_score: int) -> None:
    console.print()
    console.print(Rule("[bold magenta] GPU RESULTS — RTX 3090 Market Intelligence [/bold magenta]", style="magenta"))
    console.print()
    console.print(
        "[dim italic]Market intelligence only — purchase decision pending workstation confirmation[/dim italic]"
    )
    console.print()
    table = Table(box=None, show_header=False, padding=(0, 2))
    table.add_column(style="dim", no_wrap=True)
    table.add_column(style="bold")
    table.add_row("GPU listings fetched", str(total_fetched))
    table.add_row("After filters", str(after_discard))
    table.add_row("Scored (above threshold)", str(after_score))
    console.print(Padding(table, (0, 2)))
    console.print()


def print_gpu_new_listings(new_listings: list[dict[str, Any]]) -> None:
    if not new_listings:
        return
    console.print(Rule(f"[bold green] NEW GPU LISTINGS ({len(new_listings)}) [/bold green]", style="green"))
    console.print()
    for item in new_listings:
        console.print(_gpu_item_card(item))
        console.print()


def print_gpu_priority(items: list[dict[str, Any]]) -> None:
    priority = [i for i in items if i.get("tier") == "PRIORITY"]
    if not priority:
        return
    console.print(Rule(f"[bold red] GPU PRIORITY ({len(priority)}) [/bold red]", style="red"))
    console.print()
    for item in priority:
        console.print(_gpu_item_card(item))
        console.print()


def print_gpu_review(items: list[dict[str, Any]]) -> None:
    review = [i for i in items if i.get("tier") == "REVIEW"]
    if not review:
        return
    console.print(Rule(f"[bold yellow] GPU REVIEW ({len(review)}) [/bold yellow]", style="yellow"))
    console.print()
    for item in review:
        line = _gpu_item_card(item, compact=True)
        console.print(Padding(line, (0, 2)))
    console.print()


def print_gpu_marginal(items: list[dict[str, Any]]) -> None:
    marginal = [i for i in items if i.get("tier") == "MARGINAL"]
    if not marginal:
        return
    console.print(Rule(f"[dim] GPU MARGINAL ({len(marginal)}) [/dim]", style="dim"))
    console.print()
    for item in marginal:
        line = _gpu_item_card(item, compact=True)
        console.print(Padding(line, (0, 2)))
    console.print()


def print_gpu_disappeared(disappeared: list[dict[str, Any]], limit: int = 5) -> None:
    if not disappeared:
        return
    recent = sorted(disappeared, key=lambda x: x.get("last_seen", ""), reverse=True)[:limit]
    console.print(Rule("[dim] GPU — RECENTLY DISAPPEARED [/dim]", style="dim"))
    console.print()
    table = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="dim")
    table.add_column("Title", max_width=50)
    table.add_column("Price", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Last seen", justify="right")
    for item in recent:
        table.add_row(
            item.get("title", "")[:48],
            _format_price(item.get("price", 0)),
            str(item.get("score", 0)),
            _time_ago(item.get("last_seen", "")),
        )
    console.print(Padding(table, (0, 2)))
    console.print()


def print_gpu_full_results(
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
    """Top-level GPU display function called by gpu_hunt.py."""
    print_gpu_header(total_fetched, after_discard, len(scored_items))

    if new_only:
        if new_listings:
            print_gpu_new_listings(new_listings)
        else:
            console.print("[dim]No new GPU listings found this run.[/dim]")
            console.print()
        return

    if new_listings:
        print_gpu_new_listings(new_listings)

    print_gpu_priority(scored_items)
    print_gpu_review(scored_items)

    if show_marginal:
        print_gpu_marginal(scored_items)

    if disappeared:
        print_gpu_disappeared(disappeared)

    if not scored_items and not new_listings:
        console.print(Panel(
            "[dim]No GPU listings met the minimum score threshold this run.[/dim]",
            border_style="dim",
        ))
        console.print()

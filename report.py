"""
Terminal output formatting for Neeman's Listing Health Monitor.
Uses the `rich` library for styled, structured output.
"""

from datetime import datetime
from rich.console import Console
from rich.table import Table
from rich import box
from rich.text import Text
from rich.panel import Panel
from rich.rule import Rule

console = Console()


# ──────────────────────────────────────────────
# Status helpers
# ──────────────────────────────────────────────

STATUS_EMOJI = {
    "GREEN": "[bold green]GREEN ✅[/]",
    "YELLOW": "[bold yellow]YELLOW ⚠️[/]",
    "RED": "[bold red]RED 🔴[/]",
    "ERROR": "[bold red]ERROR ❌[/]",
}

STATUS_COLOR = {
    "GREEN": "green",
    "YELLOW": "yellow",
    "RED": "red",
    "ERROR": "red",
}


def _fmt_price(price: int | None) -> str:
    if price is None:
        return "[dim]–[/]"
    return f"₹{price:,}"


def _fmt_buy_box(buy_box: bool) -> str:
    return "✅" if buy_box else "[bold red]❌[/]"


def _fmt_list_count(lst: list) -> str:
    if not lst:
        return "[dim]0[/]"
    if lst == ["Could not parse"]:
        return "[dim]?[/]"
    return str(len(lst))


# ──────────────────────────────────────────────
# Per-product block
# ──────────────────────────────────────────────

def print_product_block(product_name: str, platforms_data: list[dict], flags: list[str], status: str) -> None:
    """
    Print a rich table block for a single product.

    platforms_data: list of dicts with keys:
        platform, price, buy_box, sizes, colors, error
    flags: list of flag strings
    status: "GREEN" | "YELLOW" | "RED" | "ERROR"
    """
    status_label = STATUS_EMOJI.get(status, status)
    color = STATUS_COLOR.get(status, "white")

    title = f"[bold]PRODUCT: {product_name}[/]  —  STATUS: {status_label}"

    table = Table(
        box=box.SIMPLE_HEAD,
        show_header=True,
        header_style="bold cyan",
        border_style=color,
        expand=False,
        padding=(0, 1),
    )
    table.add_column("Platform", style="bold", min_width=14)
    table.add_column("Price", justify="right", min_width=10)
    table.add_column("Buy Box", justify="center", min_width=9)
    table.add_column("Sizes", justify="center", min_width=7)
    table.add_column("Colors", justify="center", min_width=7)

    for pd in platforms_data:
        row_style = "dim" if pd.get("error") else ""
        table.add_row(
            pd["platform"],
            _fmt_price(pd.get("price")),
            _fmt_buy_box(pd.get("buy_box", False)),
            _fmt_list_count(pd.get("sizes", [])),
            _fmt_list_count(pd.get("colors", [])),
            style=row_style,
        )

    console.print(Panel(table, title=title, border_style=color, expand=False))

    if flags:
        console.print("  [bold yellow]⚠ FLAGS:[/]")
        for flag in flags:
            console.print(f"    [yellow]→[/] {flag}")
    else:
        console.print("  [green]✓ No flags[/]")

    console.print()


# ──────────────────────────────────────────────
# Header banner
# ──────────────────────────────────────────────

def print_header(timestamp: str, products_checked: int, platforms_checked: int, flags_raised: int) -> None:
    console.print()
    console.rule("[bold cyan]NEEMAN'S LISTING HEALTH REPORT[/]", style="cyan")
    console.print(f"  [dim]Run:[/] {timestamp}")
    console.print(
        f"  [bold green]{products_checked}[/] products checked  |  "
        f"[bold blue]{platforms_checked}[/] platforms checked  |  "
        f"[bold {'red' if flags_raised else 'green'}]{flags_raised}[/] flags raised"
    )
    console.rule(style="cyan")
    console.print()


# ──────────────────────────────────────────────
# Master flags summary
# ──────────────────────────────────────────────

def print_master_summary(all_flags: dict[str, list[str]]) -> None:
    """
    all_flags: { product_name: [flag1, flag2, ...], ... }
    """
    console.rule("[bold]MASTER FLAGS SUMMARY[/]", style="dim")
    any_flags = False
    for product, flags in all_flags.items():
        if flags:
            any_flags = True
            console.print(f"  [bold]{product}[/]")
            for flag in flags:
                console.print(f"    [yellow]→[/] {flag}")
    if not any_flags:
        console.print("  [green]All listings healthy — no flags raised.[/]")
    console.print()


# ──────────────────────────────────────────────
# Dry-run output
# ──────────────────────────────────────────────

def print_dry_run(catalog_rows: list) -> None:
    console.rule("[bold cyan]DRY RUN — listings that would be scraped[/]", style="cyan")

    table = Table(box=box.SIMPLE_HEAD, header_style="bold cyan", expand=False)
    table.add_column("#", justify="right", style="dim", width=4)
    table.add_column("Product", min_width=20)
    table.add_column("Platform", min_width=14)
    table.add_column("URL", min_width=40, no_wrap=False)

    for i, row in enumerate(catalog_rows, 1):
        table.add_row(str(i), row.product_name, row.platform_name, row.url)

    console.print(table)
    console.print(f"\n  [bold]{len(catalog_rows)}[/] listings would be scraped.\n")

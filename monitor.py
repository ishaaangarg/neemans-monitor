"""
Neeman's Listing Health Monitor — CLI entry point.
─────────────────────────────────────────────────────
HOW TO ADD A NEW PLATFORM
──────────────────────────
Step 1 — Google Sheet ("Catalog" tab):
    Add a new row:
        | Product Name | NewPlatform | https://newplatform.com/product-url | TRUE |
    No code changes needed to scrape it. The generic parser handles it
    automatically (price + buy-box detection).

Step 2 (optional — for precise size/color data) — parsers.py:
    1. Write a function:
           def parse_newplatform_com(soup: BeautifulSoup) -> dict:
               ...
               return {"price": ..., "buy_box": ..., "sizes": [...], "colors": [...], "error": None}
    2. Register it in PARSER_REGISTRY at the bottom of parsers.py:
           "newplatform.com": parse_newplatform_com,
    Next run will use your custom parser automatically.
─────────────────────────────────────────────────────
"""

import click
from dotenv import load_dotenv

from core import collect_product_flags, product_status, run_scrape
from report import (
    console,
    print_dry_run,
    print_header,
    print_master_summary,
    print_product_block,
)
from sheets import read_catalog, write_report_rows

load_dotenv()


@click.command()
@click.option("--all", "run_all", is_flag=True, default=False, help="Scrape all active listings.")
@click.option("--product", default=None, metavar="NAME", help='Scrape a specific product, e.g. "Knit Runner".')
@click.option("--platform", default=None, metavar="NAME", help='Scrape all products on a platform, e.g. "Myntra".')
@click.option("--dry-run", "dry_run", is_flag=True, default=False, help="Show what would be scraped, no API calls.")
def cli(run_all: bool, product: str | None, platform: str | None, dry_run: bool) -> None:
    """Neeman's Listing Health Monitor — check product listings across all platforms."""

    if not any([run_all, product, platform, dry_run]):
        raise click.UsageError(
            "Specify one of: --all | --product NAME | --platform NAME | --dry-run"
        )

    console.print("[bold cyan]Loading catalog from Google Sheets …[/]")
    try:
        catalog = read_catalog(skip_inactive=True)
    except Exception as exc:
        console.print(f"[red]Failed to load catalog: {exc}[/]")
        raise SystemExit(1)

    if not catalog:
        console.print("[yellow]No active listings found in the Catalog sheet.[/]")
        return

    # Apply filter
    if product:
        filtered = [r for r in catalog if r.product_name.lower() == product.lower()]
        if not filtered:
            console.print(f"[yellow]No active listings found for product: {product}[/]")
            return
    elif platform:
        filtered = [r for r in catalog if r.platform_name.lower() == platform.lower()]
        if not filtered:
            console.print(f"[yellow]No active listings found for platform: {platform}[/]")
            return
    else:
        filtered = catalog

    if dry_run:
        print_dry_run(filtered)
        return

    def _progress(product_name, platform_name, idx, total):
        console.print(
            f"  [{idx + 1}/{total}] [dim]Scraping[/] [bold]{product_name}[/] "
            f"on [cyan]{platform_name}[/] …"
        )

    all_results, flags_by_product, timestamp = run_scrape(filtered, progress_callback=_progress)

    # Group for display
    products_seen = list(dict.fromkeys(r["product_name"] for r in all_results))
    total_flags = sum(len(f) for f in flags_by_product.values())

    print_header(timestamp, len(products_seen), len(all_results), total_flags)

    for prod in products_seen:
        prod_results = [r for r in all_results if r["product_name"] == prod]
        status = product_status(prod_results)
        print_product_block(prod, prod_results, flags_by_product.get(prod, []), status)

    print_master_summary(flags_by_product)

    console.print("[dim]Writing results to Google Sheets …[/]")
    try:
        write_report_rows(all_results, timestamp)
        console.print("[green]✓ Results written to Reports sheet.[/]\n")
    except Exception as exc:
        console.print(f"[red]✗ Failed to write to Google Sheets: {exc}[/]\n")


if __name__ == "__main__":
    cli()

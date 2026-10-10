"""Contabo storefront pricing report (no API key): VPS/VDS price table.

Scrapes https://contabo.com/en/pricing/ (Playwright by default for
Cloudflare) and prints productId-mapped prices, optionally as CSV for
feeding catalog sync jobs.

Usage:
    python examples/pricing_report.py
    python examples/pricing_report.py --fetcher direct --format csv > prices.csv
    python examples/pricing_report.py --currency EUR --format markdown
"""

from __future__ import annotations

import argparse
import csv
import sys

sys.path.insert(0, "src")

from contabo import ContaboStorefrontPricing  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetcher", default=None, help="direct, playwright, scraping_api.")
    parser.add_argument("--currency", default=None, help="Price currency (default EUR).")
    parser.add_argument("--page-url", default=None, help="Override pricing page URL.")
    parser.add_argument("--format", choices=["table", "csv", "markdown"], default="table")
    args = parser.parse_args(argv)

    overrides = {}
    if args.fetcher:
        overrides["fetcher"] = args.fetcher
    if args.currency:
        overrides["currency"] = args.currency
    if args.page_url:
        overrides["pricing_page_url"] = args.page_url
    pricing = ContaboStorefrontPricing.from_env(**overrides)
    prices = pricing.fetch()
    rows = [
        [p.product_id, p.name, str(p.cpu), str(p.ram_gb), str(p.disk_gb), str(p.unit_cost or "-"), p.currency]
        for p in sorted(prices, key=lambda p: p.product_id)
    ]
    headers = ["product_id", "name", "cpu", "ram_gb", "disk_gb", "unit_cost", "currency"]
    if args.format == "csv":
        writer = csv.writer(sys.stdout)
        writer.writerow(headers)
        writer.writerows(rows)
    elif args.format == "markdown":
        print("| " + " | ".join(headers) + " |")
        print("|" + "|".join(["---"] * len(headers)) + "|")
        for row in rows:
            print("| " + " | ".join(row) + " |")
    else:
        widths = [max(len(r[i]) for r in [headers, *rows]) for i in range(len(headers))]
        print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
        for row in rows:
            print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))
        print(f"\n{len(rows)} plan(s) quoted in {prices[0].currency if prices else '?'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

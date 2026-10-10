"""Offline tests for Contabo storefront pricing — no network."""

from decimal import Decimal

import pytest

from contabo import ContaboStorefrontPricing
from contabo.errors import PricingError
from contabo.pricing import (
    PRODUCT_ID_BY_NAME,
    name_to_product_id,
    normalize_plan_name,
    parse_pricing_page,
)

JSON_LD_HTML = """
<html><body>
<script type="application/ld+json">
{"@type": "Product", "name": "Cloud VPS 4",
 "description": "4 vCPU Cores 8 GB RAM 100 GB SSD",
 "offers": [{"@type": "AggregateOffer", "priceCurrency": "EUR", "lowPrice": 5.5}]}
</script>
<script type="application/ld+json">
{"@type": "Product", "name": "Cloud VDS S",
 "description": "6 vCPU Cores 24 GB RAM 180 GB NVMe",
 "offers": [{"@type": "AggregateOffer", "priceCurrency": "EUR", "lowPrice": "39.20"}]}
</script>
<script type="application/ld+json">
{"@type": "Product", "name": "Storage VPS 10", "offers": []}
</script>
</body></html>
"""

TABLE_HTML = """
<html><body><table>
<tr><td>Cloud VPS 6</td><td>6 vCPU Cores</td><td>12 GB RAM</td>
<td>200 GB SSD</td><td>\u20ac 7,00 / month</td></tr>
</table></body></html>
"""


def test_mapping_covers_api_product_ids():
    for pid in ("V153", "V158", "V159", "V164", "V8", "V16"):
        assert pid in PRODUCT_ID_BY_NAME.values()
    assert "V93" not in PRODUCT_ID_BY_NAME.values()  # Storage excluded
    assert name_to_product_id("Cloud\u00a0VPS\u00a04") == "V153"
    assert normalize_plan_name("  Cloud VPS Plus  18 ") == "cloud vps plus 18"


def test_json_ld_parse_wins():
    prices = parse_pricing_page(JSON_LD_HTML, currency="EUR")
    by_id = {p.product_id: p for p in prices}
    assert by_id["V153"].unit_cost == Decimal("5.5")
    assert by_id["V153"].currency == "EUR"
    assert by_id["V8"].unit_cost == Decimal("39.20")
    assert by_id["V8"].family == "vds"
    # Storage plan without usable offer is skipped, not fatal.
    assert all(p.product_id in PRODUCT_ID_BY_NAME.values() for p in prices)


def test_table_fallback_parse():
    prices = parse_pricing_page(TABLE_HTML, currency="EUR")
    assert len(prices) == 1
    assert prices[0].product_id == "V154"
    assert prices[0].unit_cost == Decimal("7.00")


def test_empty_page_raises():
    with pytest.raises(PricingError):
        parse_pricing_page("<html><body>no plans here</body></html>")


def test_zero_price_dropped_then_raises_when_none_usable():
    html = """
    <script type="application/ld+json">
    {"@type": "Product", "name": "Cloud VPS 4",
     "offers": [{"@type": "AggregateOffer", "priceCurrency": "EUR", "lowPrice": 0}]}
    </script>
    """
    with pytest.raises(PricingError):
        parse_pricing_page(html)


def test_fetch_with_custom_callable():
    pricing = ContaboStorefrontPricing.from_env(fetcher="direct")
    prices = pricing.fetch_with(lambda: JSON_LD_HTML)
    assert {p.product_id for p in prices} == {"V153", "V8"}


def test_spec_parsing_is_keyword_anchored():
    from contabo.pricing import _parse_spec_numbers

    assert _parse_spec_numbers("4 vCPU Cores 8 GB RAM 100 GB SSD") == {
        "cpu": 4, "ram_gb": 8.0, "disk_gb": 100,
    }
    # RAM must not be mistaken for disk.
    assert _parse_spec_numbers("6 vCPU Cores 12 GB RAM 200 GB SSD")["disk_gb"] == 200
    # VDS phrasings.
    assert _parse_spec_numbers("3 Physical CPU Cores, 24 GB RAM, 180 GB NVMe SSD")["cpu"] == 3
    assert _parse_spec_numbers("6 Cores, 48GB Ram, 360GB NVMe")["cpu"] == 6
    assert _parse_spec_numbers("EPYC 7282 8 Core, 64GB Ram with 480GB NVMe")["cpu"] == 8

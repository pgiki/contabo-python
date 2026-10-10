"""Storefront pricing (contabo.com/en/pricing): VPS/VDS prices, no API key.

Contabo exposes no product/pricing API, so prices are scraped from the
public pricing page. The page is Astro SSR HTML with per-plan
``script[type="application/ld+json"]`` blocks::

    {"@type": "Product", "name": "Cloud VPS 4",
     "offers": [{"@type": "AggregateOffer", "priceCurrency": "EUR",
                 "lowPrice": 5.5}]}

plus HTML tables/cards (``Model|CPU|RAM|Storage|Port|Price``). The
``productId`` (V153…) → storefront-name mapping comes from the
``POST /v1/compute/instances`` description table in the Redoc UI at
https://api.contabo.com/ (no unauthenticated OpenAPI JSON available).

Cloudflare note: plain HTTP GETs (``fetcher="direct"``) only work while
bot-management cookies are fresh. The default ``fetcher="playwright"``
(optional ``pricing`` extra) loads the pricing page in real Chrome,
which carries Chrome's TLS fingerprint and auto-refreshed cookies.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from html import unescape
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from .errors import PricingError

DEFAULT_PRICING_PAGE_URL = "https://contabo.com/en/pricing/"
DEFAULT_CURRENCY = "EUR"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/154.0.0.0 Safari/537.36"
)

#: Storefront name → Contabo productId (Redoc Create-instance table).
#: Storage VPS (V93…) intentionally excluded — not provisionable via API.
PRODUCT_ID_BY_NAME: dict[str, str] = {
    "cloud vps 4": "V153",
    "cloud vps 6": "V154",
    "cloud vps 8": "V155",
    "cloud vps 12": "V156",
    "cloud vps 16": "V157",
    "cloud vps 18": "V158",
    "cloud vps plus 4": "V159",
    "cloud vps plus 6": "V160",
    "cloud vps plus 8": "V161",
    "cloud vps plus 12": "V162",
    "cloud vps plus 16": "V163",
    "cloud vps plus 18": "V164",
    "cloud vds s": "V8",
    "cloud vds m": "V9",
    "cloud vds l": "V10",
    "cloud vds xl": "V11",
    "cloud vds xxl": "V16",
}

NAME_BY_PRODUCT_ID: dict[str, str] = {v: k for k, v in PRODUCT_ID_BY_NAME.items()}

#: productId → family slug used by fikashop catalog tiers.
FAMILY_BY_PRODUCT_ID: dict[str, str] = {
    "V153": "vps", "V154": "vps", "V155": "vps",
    "V156": "vps", "V157": "vps", "V158": "vps",
    "V159": "plus", "V160": "plus", "V161": "plus",
    "V162": "plus", "V163": "plus", "V164": "plus",
    "V8": "vds", "V9": "vds", "V10": "vds", "V11": "vds", "V16": "vds",
}


class PricingConfig(BaseModel):
    """Contabo storefront pricing configuration with validation."""

    pricing_page_url: str = Field(
        default=DEFAULT_PRICING_PAGE_URL,
        description="Contabo pricing page (Playwright entry point)",
    )
    currency: str = Field(default=DEFAULT_CURRENCY, description="Price currency (EUR)")
    locale: str = Field(default="en", description="Storefront locale (en, en-us, de)")
    timeout: float = Field(default=30.0, description="Request timeout in seconds")
    request_delay: float = Field(default=1.0, ge=0, description="Politeness delay (seconds)")
    fetcher: str = Field(default="playwright", description="Transport: direct, playwright, scraping_api")
    cookies: dict[str, str] = Field(default_factory=dict, description="Static cookies for direct fetcher")
    scrape_api_url: str = Field(default="", description="Scraping-proxy URL")
    scrape_api_key: str = Field(default="", description="Scraping-proxy API key")

    model_config = ConfigDict(str_strip_whitespace=True, validate_default=True)

    @classmethod
    def from_env(cls, **overrides: Any) -> PricingConfig:
        """Build config from explicit args with ``CONTABO_PRICING_*`` env fallback."""
        env = os.environ.get
        cookies = overrides.get("cookies")
        if cookies is None:
            cookies = _parse_cookies(env("CONTABO_PRICING_COOKIES", ""))
        return cls(
            pricing_page_url=overrides.get("pricing_page_url")
            or env("CONTABO_PRICING_PAGE_URL", "")
            or DEFAULT_PRICING_PAGE_URL,
            currency=(overrides.get("currency") or env("CONTABO_PRICING_CURRENCY", "") or DEFAULT_CURRENCY).upper(),
            locale=overrides.get("locale") or env("CONTABO_PRICING_LOCALE", "") or "en",
            timeout=overrides.get("timeout")
            if overrides.get("timeout") is not None
            else float(env("CONTABO_PRICING_TIMEOUT", "") or 30.0),
            request_delay=overrides.get("request_delay")
            if overrides.get("request_delay") is not None
            else float(env("CONTABO_PRICING_DELAY", "") or 1.0),
            fetcher=(overrides.get("fetcher") or env("CONTABO_PRICING_FETCHER", "") or "playwright").lower(),
            cookies=cookies,
            scrape_api_url=overrides.get("scrape_api_url") or env("CONTABO_PRICING_SCRAPE_API_URL", ""),
            scrape_api_key=overrides.get("scrape_api_key") or env("CONTABO_PRICING_SCRAPE_API_KEY", ""),
        )


class VpsPrice(BaseModel):
    """One scraped VPS/VDS plan price (unit cost basis, base region, 1-mo)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str = Field(description="Contabo productId, e.g. V153")
    name: str = Field(description="Storefront plan name, e.g. Cloud VPS 4")
    family: str = Field(default="", description="vps|plus|vds")
    cpu: int = Field(default=0)
    ram_gb: float = Field(default=0)
    disk_gb: int = Field(default=0)
    unit_cost: Decimal | None = Field(default=None, description="Monthly cost basis incl. VAT (see currency)")
    currency: str = Field(default=DEFAULT_CURRENCY)


def normalize_plan_name(raw: str) -> str:
    """``Cloud VPS 4`` → ``cloud vps 4`` (NBSP/whitespace/case insensitive)."""
    text = unescape(str(raw or "")).replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def name_to_product_id(name: str) -> str | None:
    return PRODUCT_ID_BY_NAME.get(normalize_plan_name(name))


def product_id_to_name(product_id: str) -> str | None:
    return NAME_BY_PRODUCT_ID.get(str(product_id or "").strip().upper())


def _parse_cookies(raw: Any) -> dict[str, str]:
    if isinstance(raw, dict):
        return dict(raw)
    out: dict[str, str] = {}
    for part in str(raw or "").split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            k, v = k.strip(), v.strip()
            if k:
                out[k] = v
    return out


def _parse_amount(raw: Any) -> Decimal | None:
    """Promo-applied amount; ``0``/empty means unavailable (never store 0)."""
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return None
    if value <= 0:
        return None
    return value


def _parse_spec_numbers(text: str) -> dict[str, Any]:
    """Extract cpu/ram/disk from strings like ``4 vCPU Cores 8 GB RAM 100 GB SSD``.

    Keyword-anchored: cpu = number before ``vCPU|Virtual Cores|Physical CPU
    Cores|Cores``, RAM = number before ``RAM``, disk = number before
    ``SSD|NVMe|HDD|Storage`` (TB×1024).
    """
    out: dict[str, Any] = {}

    def _num(raw: str) -> float:
        return float(raw.replace(",", "."))

    cpu = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(?:vCPU|Virtual\s*Cores?|Physical\s*CPU\s*Cores?|(?:AMD\s*(?:EPYC\s*)?)?Cores?\b)",
        text, re.IGNORECASE,
    )
    if cpu:
        out["cpu"] = int(_num(cpu.group(1)))
    ram = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:GB|TB)\s*RAM", text, re.IGNORECASE)
    if ram:
        amount = _num(ram.group(1))
        if re.search(r"TB\s*RAM", ram.group(0), re.IGNORECASE):
            amount *= 1024
        out["ram_gb"] = amount
    disk = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(GB|TB)\s*(?:NVMe|SSD|HDD|Storage)", text, re.IGNORECASE
    )
    if disk:
        amount = _num(disk.group(1))
        if disk.group(2).upper() == "TB":
            amount *= 1024
        out["disk_gb"] = int(amount)
    return out


def parse_json_ld_blocks(html: str, *, currency: str = DEFAULT_CURRENCY) -> dict[str, dict[str, Any]]:
    """Parse ``script[type="application/ld+json"]`` Product blocks.

    Returns ``{normalized_name: {name, unit_cost, currency, specs}}``.
    """
    out: dict[str, dict[str, Any]] = {}
    cur = currency.upper()
    for match in re.finditer(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html, re.DOTALL | re.IGNORECASE,
    ):
        raw = match.group(1).strip()
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        blocks = payload if isinstance(payload, list) else [payload]
        for block in blocks:
            if not isinstance(block, dict):
                continue
            types = block.get("@type")
            type_list = types if isinstance(types, list) else [types]
            if "Product" not in [str(t) for t in type_list]:
                continue
            name = str(block.get("name") or "").strip()
            if not name:
                continue
            key = normalize_plan_name(name)
            if key not in PRODUCT_ID_BY_NAME:
                continue
            offers = block.get("offers") or []
            if isinstance(offers, dict):
                offers = [offers]
            price: Decimal | None = None
            offer_currency = cur
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                otype = str(offer.get("@type") or "")
                if otype not in ("Offer", "AggregateOffer"):
                    continue
                ocur = str(offer.get("priceCurrency") or "").strip().upper()
                if ocur and ocur != cur:
                    continue
                for amount_key in ("lowPrice", "price"):
                    candidate = _parse_amount(offer.get(amount_key))
                    if candidate is not None:
                        price = candidate
                        offer_currency = ocur or cur
                        break
                if price is not None:
                    break
            if price is None:
                continue
            specs = _parse_spec_numbers(str(block.get("description") or ""))
            out[key] = {"name": name, "unit_cost": price, "currency": offer_currency, **specs}
    return out


def parse_html_tables(html: str, *, currency: str = DEFAULT_CURRENCY) -> dict[str, dict[str, Any]]:
    """Fallback: parse ``Model|CPU|RAM|Storage|Price`` tables and cards.

    Returns same shape as :func:`parse_json_ld_blocks`; JSON-LD wins on merge.
    """
    out: dict[str, dict[str, Any]] = {}
    text = unescape(html).replace("\xa0", " ")
    # Table rows mentioning a known plan name + a price like €4.40 / 4,40 €.
    for match in re.finditer(
        r"(Cloud\s+(?:VPS\s+(?:Plus\s+)?\d+|VDS\s+S|VDS\s+M|VDS\s+L|VDS\s+XL|VDS\s+XXL))"
        r"(.{0,400}?)"
        r"(?:€\s*(\d+(?:[.,]\d+)?)|(\d+(?:[.,]\d+)?)\s*€)",
        text, re.IGNORECASE | re.DOTALL,
    ):
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        key = normalize_plan_name(name)
        if key not in PRODUCT_ID_BY_NAME:
            continue
        amount_raw = match.group(3) or match.group(4)
        price = _parse_amount((amount_raw or "").replace(",", "."))
        if price is None or key in out:
            continue
        specs = _parse_spec_numbers(match.group(2))
        out[key] = {"name": name, "unit_cost": price, "currency": currency.upper(), **specs}
    return out


def parse_pricing_page(html: str, *, currency: str = DEFAULT_CURRENCY) -> list[VpsPrice]:
    """Parse a pricing page into :class:`VpsPrice` list (JSON-LD wins over tables)."""
    cur = currency.upper()
    merged = parse_html_tables(html, currency=cur)
    merged.update(parse_json_ld_blocks(html, currency=cur))
    if not merged:
        raise PricingError("Contabo pricing page yielded no recognizable plans.")
    prices: list[VpsPrice] = []
    for key, vals in merged.items():
        product_id = PRODUCT_ID_BY_NAME.get(key)
        if not product_id:
            continue
        prices.append(
            VpsPrice(
                product_id=product_id,
                name=str(vals.get("name") or key),
                family=FAMILY_BY_PRODUCT_ID.get(product_id, ""),
                cpu=int(vals.get("cpu") or 0),
                ram_gb=float(vals.get("ram_gb") or 0),
                disk_gb=int(vals.get("disk_gb") or 0),
                unit_cost=vals.get("unit_cost"),
                currency=str(vals.get("currency") or cur).upper(),
            )
        )
    # Drop unavailable legs, keep deterministic order by productId.
    prices = [p for p in prices if p.unit_cost is not None]
    if not prices:
        raise PricingError("Contabo pricing page has no usable EUR prices.")
    return sorted(prices, key=lambda p: p.product_id)


class PlaywrightPricingSession:
    """One browser + page reused for pricing page loads."""

    def __init__(self, config: PricingConfig) -> None:
        self.config = config
        self._stack: Any = None
        self._page: Any = None

    def __enter__(self) -> PlaywrightPricingSession:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore # noqa: PLC0415
        except ImportError as exc:
            raise PricingError(
                "Playwright fetcher requested but `playwright` is not installed "
                "(pip install contabo-python[pricing] && playwright install chromium)."
            ) from exc
        try:
            self._stack = sync_playwright()
            p = self._stack.__enter__()
            try:
                browser = p.chromium.launch(headless=True, channel="chrome")
            except Exception:
                browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
            self._page = context.new_page()
            self._page.goto(
                self.config.pricing_page_url,
                wait_until="domcontentloaded",
                timeout=int(self.config.timeout * 1000),
            )
            self._page.wait_for_timeout(8000)
        except Exception as exc:
            self.close()
            if isinstance(exc, PricingError):
                raise
            raise PricingError(f"Playwright pricing session failed: {exc}") from exc
        return self

    def html(self) -> str:
        if self._page is None:
            raise PricingError("Playwright session is not open (use as context manager).")
        try:
            return str(self._page.content())
        except Exception as exc:
            raise PricingError(f"Playwright page read failed: {exc}") from exc

    def close(self) -> None:
        stack, self._stack = self._stack, None
        self._page = None
        if stack is not None:
            with contextlib.suppress(Exception):
                stack.__exit__(None, None, None)

    def __exit__(self, *args: object) -> None:
        self.close()


class ContaboStorefrontPricing:
    """VPS/VDS prices from the Contabo storefront pricing page (keyless).

    Example:
        >>> pricing = ContaboStorefrontPricing()  # fetcher="playwright"
        >>> prices = pricing.fetch()
        >>> [(p.product_id, p.unit_cost) for p in prices]
    """

    def __init__(self, config: PricingConfig | None = None, **overrides: Any) -> None:
        if config is not None and overrides:
            config = config.model_copy(update=overrides)
        self.config = config if config is not None else PricingConfig.from_env(**overrides)

    @classmethod
    def from_env(cls, **overrides: Any) -> ContaboStorefrontPricing:
        return cls(PricingConfig.from_env(**overrides))

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "text/html,application/xhtml+xml",
            "user-agent": USER_AGENT,
        }

    def _fetch_direct(self) -> str:
        try:
            r = httpx.get(
                self.config.pricing_page_url,
                headers=self._headers(),
                cookies=self.config.cookies or None,
                timeout=self.config.timeout,
            )
        except Exception as exc:
            raise PricingError(f"Contabo pricing request failed: {exc}") from exc
        if r.status_code in (401, 403):
            raise PricingError(
                f"Contabo pricing blocked (HTTP {r.status_code}; Cloudflare/cookies need refresh)."
            )
        if r.status_code != 200:
            raise PricingError(f"Contabo pricing HTTP {r.status_code}.")
        return r.text

    def _fetch_playwright(self) -> str:
        with PlaywrightPricingSession(self.config) as session:
            return session.html()

    def _fetch_scraping_api(self) -> str:
        if not self.config.scrape_api_url or not self.config.scrape_api_key:
            raise PricingError("Scraping-API fetcher requested but scrape_api_url/key are not configured.")
        try:
            r = httpx.post(
                self.config.scrape_api_url,
                json={"url": self.config.pricing_page_url, "method": "GET", "headers": self._headers()},
                headers={
                    "Authorization": f"Bearer {self.config.scrape_api_key}",
                    "content-type": "application/json",
                },
                timeout=self.config.timeout + 30,
            )
        except Exception as exc:
            raise PricingError(f"Scraping API request failed: {exc}") from exc
        if r.status_code != 200:
            raise PricingError(f"Scraping API HTTP {r.status_code}.")
        try:
            payload = r.json()
        except Exception:
            return r.text
        if isinstance(payload, dict):
            for key in ("html", "content", "result"):
                val = payload.get(key)
                if isinstance(val, str) and len(val) > 1000:
                    return val
                if isinstance(val, dict) and isinstance(val.get("html"), str):
                    return val["html"]
        raise PricingError("Scraping API did not return page HTML.")

    def html(self, fetcher: str | None = None) -> str:
        name = (fetcher or self.config.fetcher).lower()
        if name == "playwright":
            return self._fetch_playwright()
        if name in ("scraping_api", "scraping-api", "api"):
            return self._fetch_scraping_api()
        return self._fetch_direct()

    def fetch(self, *, fetcher: str | None = None) -> list[VpsPrice]:
        """Fetch and parse all VPS/VDS plan prices."""
        html = self.html(fetcher=fetcher)
        if self.config.request_delay:
            time.sleep(self.config.request_delay)
        return parse_pricing_page(html, currency=self.config.currency)

    def fetch_with(self, post: Callable[[], str]) -> list[VpsPrice]:
        """Parse HTML from a custom callable (tests / proxies)."""
        return parse_pricing_page(post(), currency=self.config.currency)

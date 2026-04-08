"""Scrape TAIFEX margin requirements and sync to database."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import requests
import structlog
from bs4 import BeautifulSoup

from src.data.db import Database, MarginSnapshot

logger = structlog.get_logger(__name__)

TAIFEX_INDEX_MARGIN_URL = "https://www.taifex.com.tw/cht/5/indexMarging"

# Map Chinese product names on the TAIFEX page to our internal symbol codes
_PRODUCT_NAME_TO_SYMBOL: dict[str, str] = {
    "臺股期貨": "TX",
    "小型臺指": "MTX",
    "微型臺指期貨": "MXF",
}


@dataclass
class ScrapedMargin:
    symbol: str
    margin_initial: float
    margin_maintenance: float


def scrape_taifex_margins(
    url: str = TAIFEX_INDEX_MARGIN_URL,
    timeout: float = 15.0,
) -> list[ScrapedMargin]:
    """Fetch and parse the TAIFEX index margin page. Returns margin data for known symbols."""
    resp = requests.get(url, timeout=timeout)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = soup.find("table")
    if table is None:
        raise ValueError("No table found on TAIFEX margin page")
    results: list[ScrapedMargin] = []
    rows = table.find_all("tr")  # type: ignore[union-attr]
    for row in rows[1:]:
        cells = [c.get_text(strip=True) for c in row.find_all("td")]
        if len(cells) < 4:
            continue
        product_name = cells[0]
        symbol = _PRODUCT_NAME_TO_SYMBOL.get(product_name)
        if symbol is None:
            continue
        margin_maintenance = float(cells[2].replace(",", ""))
        margin_initial = float(cells[3].replace(",", ""))
        results.append(ScrapedMargin(
            symbol=symbol,
            margin_initial=margin_initial,
            margin_maintenance=margin_maintenance,
        ))
    if not results:
        raise ValueError("No matching products found in TAIFEX margin table")
    return results


def sync_margins(db: Database, url: str = TAIFEX_INDEX_MARGIN_URL) -> int:
    """Scrape current margins and insert snapshots for symbols whose values changed.

    Returns the number of new snapshots inserted.
    """
    scraped = scrape_taifex_margins(url=url)
    now = datetime.now(UTC)
    inserted = 0
    for item in scraped:
        latest = db.get_latest_margin(item.symbol)
        if latest and (
            latest.margin_initial == item.margin_initial
            and latest.margin_maintenance == item.margin_maintenance
        ):
            logger.debug("margin_unchanged", symbol=item.symbol)
            continue
        snapshot = MarginSnapshot(
            symbol=item.symbol,
            scraped_at=now,
            margin_initial=item.margin_initial,
            margin_maintenance=item.margin_maintenance,
            source="taifex_web",
        )
        db.add_margin_snapshot(snapshot)
        logger.info(
            "margin_updated", symbol=item.symbol,
            initial=item.margin_initial, maintenance=item.margin_maintenance,
        )
        inserted += 1
    return inserted

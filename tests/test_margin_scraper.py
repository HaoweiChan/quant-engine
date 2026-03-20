"""Tests for TAIFEX margin scraper and sync logic."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from src.data.db import Database
from src.data.margin_scraper import scrape_taifex_margins, sync_margins

FAKE_HTML = """
<html><body>
<table>
<tr><th>商品別</th><th>結算保證金</th><th>維持保證金</th><th>原始保證金</th></tr>
<tr><td>臺股期貨</td><td>336,000</td><td>348,000</td><td>454,000</td></tr>
<tr><td>小型臺指</td><td>84,000</td><td>87,000</td><td>113,500</td></tr>
<tr><td>客製化小型臺指期貨</td><td>84,000</td><td>87,000</td><td>113,500</td></tr>
<tr><td>微型臺指期貨</td><td>16,800</td><td>17,400</td><td>22,700</td></tr>
<tr><td>電子期貨</td><td>200,000</td><td>210,000</td><td>280,000</td></tr>
</table>
</body></html>
"""


class FakeResponse:
    status_code = 200
    text = FAKE_HTML
    encoding = "utf-8"

    def raise_for_status(self) -> None:
        pass


@pytest.fixture()
def db() -> Database:
    return Database(url="sqlite:///:memory:")


class TestScraper:
    def test_parse_known_symbols(self) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            results = scrape_taifex_margins()
        symbols = {r.symbol for r in results}
        assert symbols == {"TX", "MTX", "MXF"}

    def test_tx_margins_parsed(self) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            results = scrape_taifex_margins()
        tx = next(r for r in results if r.symbol == "TX")
        assert tx.margin_initial == 454_000.0
        assert tx.margin_maintenance == 348_000.0

    def test_mtx_margins_parsed(self) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            results = scrape_taifex_margins()
        mtx = next(r for r in results if r.symbol == "MTX")
        assert mtx.margin_initial == 113_500.0
        assert mtx.margin_maintenance == 87_000.0

    def test_empty_table_raises(self) -> None:
        empty_html = "<html><body><table><tr><th>A</th></tr></table></body></html>"
        fake = FakeResponse()
        fake.text = empty_html
        with (
            patch("src.data.margin_scraper.requests.get", return_value=fake),
            pytest.raises(ValueError, match="No matching products"),
        ):
            scrape_taifex_margins()


class TestSyncMargins:
    def test_first_sync_inserts_all(self, db: Database) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            inserted = sync_margins(db)
        assert inserted == 3
        assert db.get_latest_margin("TX") is not None
        assert db.get_latest_margin("MTX") is not None

    def test_no_change_skips_insert(self, db: Database) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            sync_margins(db)
            inserted = sync_margins(db)
        assert inserted == 0

    def test_changed_margin_inserts_new_row(self, db: Database) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            sync_margins(db)

        updated_html = FAKE_HTML.replace("454,000", "500,000")
        updated_resp = FakeResponse()
        updated_resp.text = updated_html
        with patch("src.data.margin_scraper.requests.get", return_value=updated_resp):
            inserted = sync_margins(db)
        assert inserted >= 1
        latest = db.get_latest_margin("TX")
        assert latest is not None
        assert latest.margin_initial == 500_000.0

    def test_margin_history_accumulates(self, db: Database) -> None:
        with patch("src.data.margin_scraper.requests.get", return_value=FakeResponse()):
            sync_margins(db)
        updated_resp = FakeResponse()
        updated_resp.text = FAKE_HTML.replace("454,000", "500,000")
        with patch("src.data.margin_scraper.requests.get", return_value=updated_resp):
            sync_margins(db)
        history = db.get_margin_history("TX")
        assert len(history) == 2

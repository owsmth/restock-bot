from __future__ import annotations

from datetime import UTC, datetime

import pytest

from restock.bot.commands.common import (
    CommandInputError,
    parse_product,
    parse_retailer,
    parse_store_id,
)
from restock.bot.formatting import format_recent, format_report_receipt, format_store
from restock.db.models import ProductCategory, Retailer
from restock.db.session import SessionFactory
from restock.services.reports import ReportService
from restock.services.stores import StoreService

pytestmark = pytest.mark.integration


def test_parse_helpers_reject_bad_values_and_accept_choices() -> None:
    assert parse_store_id("42") == 42
    assert parse_product("etb") is ProductCategory.ETB
    assert parse_retailer("target") is Retailer.TARGET
    assert parse_retailer(None) is None

    with pytest.raises(CommandInputError, match="autocomplete"):
        parse_store_id("not-a-store")
    with pytest.raises(CommandInputError, match="product"):
        parse_product("not-a-product")
    with pytest.raises(CommandInputError, match="retailer"):
        parse_retailer("not-a-retailer")


def test_report_and_recent_command_flow(
    session_factory: SessionFactory,
    seeded_source: int,
    seeded_store: int,
) -> None:
    del seeded_source
    fixed_now = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)
    report_service = ReportService(
        session_factory,
        reporter_hash_salt="test-salt-at-least-sixteen-characters",
        clock=lambda: fixed_now,
    )
    store_service = StoreService(session_factory)

    store_id = parse_store_id(str(seeded_store))
    category = parse_product("etb")
    receipt = report_service.submit_report(
        reporter_id=123,
        store_id=store_id,
        product_category=category,
        in_stock=True,
        minutes_ago=0,
        note="Command-flow test",
    )
    confirmation = format_report_receipt(receipt)
    assert "Report `#1`" in confirmation
    assert "Nothing was posted publicly" in confirmation

    stores = store_service.list_active()
    store_listing = format_store(stores)
    assert f"`#{seeded_store}`" in store_listing

    recent = report_service.list_recent(store_id=store_id)
    recent_listing = format_recent(recent)
    assert "Command-flow test" in recent_listing
    assert "Discord report" in recent_listing
    assert "11:00 AM EDT" in recent_listing

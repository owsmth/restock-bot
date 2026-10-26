from __future__ import annotations

from datetime import UTC, datetime

from restock.bot.formatting import (
    format_help,
    format_recent,
    format_report_receipt,
    format_store,
    product_label,
    retailer_label,
)
from restock.db.models import ProductCategory, RestockRegime, Retailer
from restock.services.reports import RecentReport, RecentReports, ReportReceipt
from restock.services.stores import StoreSummary


def test_store_listing_includes_ids_and_retailer() -> None:
    stores = [
        StoreSummary(
            id=7,
            retailer=Retailer.TARGET,
            name="EXAMPLE Target Cape Coral",
            address="1 Example Retail Way",
            city="Cape Coral",
            timezone="America/New_York",
            restock_regime=RestockRegime.SCHEDULED,
        )
    ]

    content = format_store(stores)

    assert "`#7`" in content
    assert "EXAMPLE Target Cape Coral" in content
    assert "Target" in content
    assert "Cape Coral" in content


def test_empty_store_listing_is_friendly() -> None:
    assert "No active stores" in format_store([])


def test_receipt_uses_store_timezone_and_stays_private() -> None:
    receipt = ReportReceipt(
        observation_id=42,
        store_name="EXAMPLE Target Cape Coral",
        store_city="Cape Coral",
        store_timezone="America/New_York",
        product_category=ProductCategory.ETB,
        in_stock=True,
        observed_at=datetime(2026, 10, 26, 15, 0, tzinfo=UTC),
        reported_at=datetime(2026, 10, 26, 15, 10, tzinfo=UTC),
    )

    content = format_report_receipt(receipt)

    assert "`#42`" in content
    assert "Elite Trainer Box (ETB)" in content
    assert "in stock" in content
    assert "Mon Oct 26, 11:00 AM EDT" in content
    assert "Nothing was posted publicly" in content

    shared_content = format_report_receipt(receipt, announced_publicly=True)
    assert "shared to the community feed without your identity" in shared_content
    assert "Nothing was posted publicly" not in shared_content


def test_recent_reports_show_est_and_simulator_label() -> None:
    reports = RecentReports(
        store_id=1,
        store_name="EXAMPLE Target Cape Coral",
        store_timezone="America/New_York",
        reports=(
            RecentReport(
                observation_id=2,
                product_category=ProductCategory.BOOSTER_BOX,
                in_stock=False,
                observed_at=datetime(2026, 12, 7, 15, 0, tzinfo=UTC),
                reported_at=datetime(2026, 12, 7, 15, 30, tzinfo=UTC),
                source_name="simulator",
                notes="Synthetic report",
            ),
            RecentReport(
                observation_id=1,
                product_category=ProductCategory.ETB,
                in_stock=True,
                observed_at=datetime(2026, 10, 26, 15, 0, tzinfo=UTC),
                reported_at=datetime(2026, 10, 26, 15, 10, tzinfo=UTC),
                source_name="discord_report",
                notes=None,
            ),
        ),
    )

    content = format_recent(reports)

    assert "Mon Oct 26, 11:00 AM EDT" in content
    assert "Mon Dec 07, 10:00 AM EST" in content
    assert "🧪 SIMULATOR" in content
    assert "Discord report" in content
    assert "> Synthetic report" in content


def test_recent_empty_state() -> None:
    reports = RecentReports(
        store_id=1,
        store_name="EXAMPLE Store",
        store_timezone="America/New_York",
        reports=(),
    )
    assert "No reports found" in format_recent(reports)


def test_labels_cover_every_enum_value() -> None:
    assert all(product_label(category) for category in ProductCategory)
    assert all(retailer_label(retailer) for retailer in Retailer)


def test_help_mentions_public_commands() -> None:
    content = format_help()

    assert "/report" in content
    assert "/stores" in content
    assert "/recent" in content
    assert "autocomplete" in content

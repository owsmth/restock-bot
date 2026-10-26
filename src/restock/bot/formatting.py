from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from restock.db.models import ProductCategory, Retailer, SourceName
from restock.services.reports import RecentReports, ReportReceipt
from restock.services.stores import StoreSummary

PRODUCT_LABELS: dict[ProductCategory, str] = {
    ProductCategory.BOOSTER_BOX: "Booster box",
    ProductCategory.ETB: "Elite Trainer Box (ETB)",
    ProductCategory.BOOSTER_BUNDLE: "Booster bundle",
    ProductCategory.BLISTER: "Blister pack",
    ProductCategory.TIN: "Tin",
    ProductCategory.COLLECTION_BOX: "Collection box",
    ProductCategory.OTHER: "Other",
}

RETAILER_LABELS: dict[Retailer, str] = {
    Retailer.TARGET: "Target",
    Retailer.WALMART: "Walmart",
    Retailer.SAMS_CLUB: "Sam's Club",
    Retailer.COSTCO: "Costco",
    Retailer.BEST_BUY: "Best Buy",
    Retailer.DOLLAR_GENERAL: "Dollar General",
    Retailer.FAMILY_DOLLAR: "Family Dollar",
    Retailer.BARNES_NOBLE: "Barnes & Noble",
    Retailer.WALGREENS: "Walgreens",
    Retailer.CVS: "CVS",
    Retailer.ACE_HARDWARE: "Ace Hardware",
    Retailer.OTHER: "Other",
}

_MAX_MESSAGE_LENGTH = 1_990


def product_label(category: ProductCategory) -> str:
    return PRODUCT_LABELS[category]


def retailer_label(retailer: Retailer) -> str:
    return RETAILER_LABELS[retailer]


def format_store(stores: list[StoreSummary]) -> str:
    if not stores:
        return "No active stores are configured yet. Ask an operator to run the seed script."
    lines = [f"**Active stores ({len(stores)})**"]
    lines.extend(
        f"`#{store.id}` **{store.name}** — {retailer_label(store.retailer)} · "
        f"{store.city} · `{store.timezone}`"
        for store in stores
    )
    return _fit("\n".join(lines))


def format_store_autocomplete(store: StoreSummary) -> str:
    retailer = retailer_label(store.retailer)
    if store.address:
        location = store.address
        if store.city:
            location = f"{location}, {store.city}"
        label = f"{retailer} - {location}"
    else:
        label = store.name
        if store.city and store.city.casefold() not in label.casefold():
            label = f"{label}, {store.city}"
    return label[:100]


def format_help() -> str:
    return (
        "**Restock bot help**\n"
        "`/report` — save what you saw at a store: product, in/out of stock, "
        "and optional minutes ago.\n"
        "`/stores` — list active stores. Store autocomplete searches retailer, "
        "name, city, and address.\n"
        "`/recent` — show the latest reports for a store.\n"
        "Reports are crowdsourced and unverified. Use the autocomplete instead of "
        "typing a store ID."
    )


def format_report_receipt(
    receipt: ReportReceipt,
    *,
    announced_publicly: bool = False,
) -> str:
    stock = "in stock" if receipt.in_stock else "out of stock"
    observed = _local_time(receipt.observed_at, receipt.store_timezone)
    public_line = (
        "_This report was also shared to the community feed without your identity._"
        if announced_publicly
        else "_Nothing was posted publicly._"
    )
    return _fit(
        f"✅ Report `#{receipt.observation_id}` saved for "
        f"**{receipt.store_name}**.\n"
        f"{product_label(receipt.product_category)} · **{stock}** · "
        f"observed {observed}.\n"
        f"{public_line}"
    )


def format_recent(reports: RecentReports) -> str:
    if not reports.reports:
        return f"No reports found for **{reports.store_name}**."
    title = f"**Recent reports — {reports.store_name}**"
    lines = [title]
    for report in reports.reports:
        stock = "✅ in stock" if report.in_stock else "❌ out of stock"
        observed = _local_time(report.observed_at, reports.store_timezone)
        source = _format_source(report.source_name)
        line = f"`{observed}` {stock} · {product_label(report.product_category)} · source: {source}"
        if report.notes:
            line += f"\n> {report.notes}"
        lines.append(line)
    return _fit("\n".join(lines))


def _format_source(source_name: str) -> str:
    if source_name == SourceName.SIMULATOR.value:
        return "🧪 SIMULATOR"
    if source_name == SourceName.DISCORD_REPORT.value:
        return "Discord report"
    if source_name == SourceName.MANUAL_LOG.value:
        return "Manual log"
    return source_name.replace("_", " ").title()


def _local_time(value: datetime, timezone_name: str) -> str:
    timezone: tzinfo
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        timezone = UTC
    return value.astimezone(timezone).strftime("%a %b %d, %I:%M %p %Z")


def _fit(content: str, limit: int = _MAX_MESSAGE_LENGTH) -> str:
    if len(content) <= limit:
        return content
    return content[: limit - 1].rstrip() + "…"

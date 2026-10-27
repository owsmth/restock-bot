from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from restock.db.models import ProductCategory, ReportOutcome, Retailer, SourceName
from restock.services.report_parser import ParsedReport
from restock.services.reports import RecentReports, ReportReceipt
from restock.services.stores import StoreSummary

OUTCOME_LABELS: dict[ReportOutcome, str] = {
    ReportOutcome.JUST_DROPPED: "DROP",
    ReportOutcome.IN_STOCK: "IN STOCK",
    ReportOutcome.SOLD_OUT: "SOLD OUT",
    ReportOutcome.NOTHING_HERE: "NOTHING",
}

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
    Retailer.GAMESTOP: "GameStop",
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


def outcome_label(outcome: ReportOutcome | None, *, in_stock: bool | None = None) -> str:
    if outcome is not None:
        return OUTCOME_LABELS[outcome]
    if in_stock is True:
        return OUTCOME_LABELS[ReportOutcome.IN_STOCK]
    if in_stock is False:
        return OUTCOME_LABELS[ReportOutcome.SOLD_OUT]
    return "UNKNOWN"


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
        "`/report` — save a store outcome: just dropped, in stock, sold out, or "
        "nothing there. You can add a product, quantity, or text.\n"
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
    observed = _local_time(receipt.observed_at, receipt.store_timezone)
    public_line = (
        "_This report was also shared to the community feed without your identity._"
        if announced_publicly
        else "_Nothing was posted publicly._"
    )
    quantity = f" · qty: {receipt.quantity_note}" if receipt.quantity_note else ""
    return _fit(
        f"Report `#{receipt.observation_id}` saved for "
        f"**{receipt.store_name}**.\n"
        f"**{outcome_label(receipt.outcome)}** · "
        f"{product_label(receipt.product_category)}{quantity} · "
        f"observed {observed}.\n"
        f"{public_line}"
    )


def format_recent(reports: RecentReports) -> str:
    if not reports.reports:
        return f"No reports found for **{reports.store_name}**."
    title = f"**Recent reports — {reports.store_name}**"
    lines = [title]
    for report in reports.reports:
        observed = _local_time(report.observed_at, reports.store_timezone)
        source = _format_source(report.source_name)
        quantity = f" · qty: {report.quantity_note}" if report.quantity_note else ""
        label = outcome_label(report.outcome, in_stock=report.in_stock)
        line = (
            f"`{observed}` **{label}** · {product_label(report.product_category)}"
            f"{quantity} · source: {source}"
        )
        if report.notes:
            line += f"\n> {report.notes}"
        lines.append(line)
    return _fit("\n".join(lines))


def format_parsed_report(parsed: ParsedReport, store_name: str) -> str:
    lines = [
        "**Confirm free-text report**",
        f"Store: **{store_name}**",
        f"Outcome: **{outcome_label(parsed.outcome)}**",
    ]
    if parsed.products is not None:
        lines.append(f"Product: {product_label(parsed.products)}")
    if parsed.quantity_note:
        lines.append(f"Quantity: {parsed.quantity_note}")
    lines.append(f"Confidence: {parsed.confidence:.2f}")
    lines.append("Confirm to save this report.")
    return _fit("\n".join(lines))


def _format_source(source_name: str) -> str:
    if source_name == SourceName.SIMULATOR.value:
        return "SIMULATOR"
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

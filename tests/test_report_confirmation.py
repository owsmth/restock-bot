from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord

from restock.bot.views import ConfirmReportView
from restock.db.models import ProductCategory, ReportOutcome, ReportSource
from restock.services.report_parser import ParsedReport
from restock.services.reports import ReportReceipt
from restock.services.stores import StoreSummary


class FakeParser:
    def parse(self, text: str, stores: list[StoreSummary]) -> ParsedReport:
        del text, stores
        return ParsedReport(
            store_id=7,
            outcome=ReportOutcome.JUST_DROPPED,
            products=ProductCategory.ETB,
            quantity_note="3 left",
            confidence=0.9,
        )


class FakeReportService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def submit_report(self, **kwargs: Any) -> ReportReceipt:
        self.calls.append(kwargs)
        return ReportReceipt(
            observation_id=42,
            store_name="Target - Colonial Blvd",
            store_city="Fort Myers",
            store_timezone="America/New_York",
            product_category=kwargs["product_category"],
            outcome=kwargs["outcome"],
            observed_at=datetime(2026, 10, 26, 15, 0, tzinfo=UTC),
            reported_at=datetime(2026, 10, 26, 15, 0, tzinfo=UTC),
            raw_text=kwargs["raw_text"],
            report_source=kwargs["report_source"],
        )


def test_confirmation_view_saves_parser_output_as_free_text() -> None:
    parsed = FakeParser().parse("Target has ETBs", [])
    service = FakeReportService()
    view = ConfirmReportView(
        report_service=service,  # type: ignore[arg-type]
        parsed=parsed,
        raw_text="Target has ETBs",
        reporter_id=123,
    )
    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    confirm_button = next(
        child
        for child in view.children
        if isinstance(child, discord.ui.Button) and child.label == "Confirm"
    )

    callback = confirm_button.callback
    assert callback is not None
    asyncio.run(callback(interaction))

    assert service.calls == [
        {
            "reporter_id": 123,
            "store_id": 7,
            "outcome": ReportOutcome.JUST_DROPPED,
            "product_category": ProductCategory.ETB,
            "quantity_note": "3 left",
            "raw_text": "Target has ETBs",
            "report_source": ReportSource.FREETEXT,
        }
    ]
    interaction.response.edit_message.assert_awaited_once()
    assert "Report `#42`" in interaction.response.edit_message.await_args.kwargs["content"]


def test_confirmation_view_cancel_does_not_save() -> None:
    service = FakeReportService()
    view = ConfirmReportView(
        report_service=service,  # type: ignore[arg-type]
        parsed=ParsedReport(store_id=7, outcome=ReportOutcome.IN_STOCK),
        raw_text="Target has ETBs",
        reporter_id=123,
    )
    interaction = MagicMock()
    interaction.user.id = 123
    interaction.response.edit_message = AsyncMock()
    cancel_button = next(
        child
        for child in view.children
        if isinstance(child, discord.ui.Button) and child.label == "Cancel"
    )

    callback = cancel_button.callback
    assert callback is not None
    asyncio.run(callback(interaction))

    assert service.calls == []
    interaction.response.edit_message.assert_awaited_once()
    assert "cancelled" in interaction.response.edit_message.await_args.kwargs["content"]

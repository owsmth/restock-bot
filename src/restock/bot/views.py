from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog

from restock.bot.formatting import format_report_receipt
from restock.db.models import ProductCategory, ReportSource
from restock.services.errors import ServiceError
from restock.services.report_parser import ParsedReport

if TYPE_CHECKING:
    from restock.bot.notifier import ReportNotifier
    from restock.services.reports import ReportService

logger = structlog.get_logger(__name__)


class ConfirmReportView(discord.ui.View):
    def __init__(
        self,
        *,
        report_service: ReportService,
        parsed: ParsedReport,
        raw_text: str,
        reporter_id: int,
        notifier: ReportNotifier | None = None,
        timeout: float = 180.0,
    ) -> None:
        super().__init__(timeout=timeout)
        self._report_service = report_service
        self._parsed = parsed
        self._raw_text = raw_text
        self._reporter_id = reporter_id
        self._notifier = notifier

    async def interaction_check(self, interaction: discord.Interaction[discord.Client]) -> bool:
        if interaction.user.id == self._reporter_id:
            return True
        await interaction.response.send_message(
            "This confirmation belongs to someone else.",
            ephemeral=True,
        )
        return False

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self,
        interaction: discord.Interaction[discord.Client],
        button: discord.ui.Button[ConfirmReportView],
    ) -> None:
        del button
        if self._parsed.store_id is None or self._parsed.outcome is None:
            await interaction.response.send_message(
                "A store and outcome are still required before saving.",
                ephemeral=True,
            )
            return

        try:
            receipt = await asyncio.to_thread(
                self._report_service.submit_report,
                reporter_id=self._reporter_id,
                store_id=self._parsed.store_id,
                outcome=self._parsed.outcome,
                product_category=self._parsed.products or ProductCategory.OTHER,
                quantity_note=self._parsed.quantity_note,
                raw_text=self._raw_text,
                report_source=ReportSource.FREETEXT,
            )
        except ServiceError as exc:
            await interaction.response.send_message(exc.user_message, ephemeral=True)
            return
        except Exception:
            logger.exception("free_text_report_save_failed")
            await interaction.response.send_message(
                "Something went wrong while saving that report. Please try again.",
                ephemeral=True,
            )
            return

        announced_publicly = (
            await self._notifier.announce(receipt) if self._notifier is not None else False
        )
        self._disable_buttons()
        await interaction.response.edit_message(
            content=format_report_receipt(
                receipt,
                announced_publicly=announced_publicly,
            ),
            view=None,
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction[discord.Client],
        button: discord.ui.Button[ConfirmReportView],
    ) -> None:
        del button
        self._disable_buttons()
        await interaction.response.edit_message(
            content="Report cancelled. Nothing was saved.",
            view=None,
        )

    def _disable_buttons(self) -> None:
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        self.stop()

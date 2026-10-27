from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.common import (
    OUTCOME_CHOICES,
    PRODUCT_CHOICES,
    CommandInputError,
    autocomplete_stores,
    log_command_invocation,
    parse_outcome,
    parse_product,
    parse_store_id,
    send_ephemeral,
)
from restock.bot.formatting import (
    format_parsed_report,
    format_recent,
    format_report_receipt,
)
from restock.bot.views import ConfirmReportView
from restock.db.models import ProductCategory, ReportSource
from restock.services.errors import ServiceError

if TYPE_CHECKING:
    from restock.bot.client import RestockBot

logger = structlog.get_logger(__name__)

USAGE_MESSAGE = "Use /report with store and outcome, or provide text for a free-text report."
FREE_TEXT_DISABLED_MESSAGE = "Free-text reports are not enabled yet. Use store and outcome."


class ReportCommands(commands.Cog):
    def __init__(self, bot: RestockBot) -> None:
        self.bot = bot

    async def store_autocomplete(
        self,
        interaction: discord.Interaction[discord.Client],
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await autocomplete_stores(self.bot.store_service, current)

    @app_commands.command(
        name="report",
        description="Report what you saw at a store.",
    )
    @app_commands.describe(
        store="Store from the autocomplete list",
        outcome="What you observed at the store",
        products="Primary Pokemon TCG product category",
        quantity="Optional quantity note",
        text="Free-text report; use it alone when you do not have store and outcome",
    )
    @app_commands.choices(outcome=OUTCOME_CHOICES, products=PRODUCT_CHOICES)
    @app_commands.autocomplete(store=store_autocomplete)
    async def report(
        self,
        interaction: discord.Interaction[discord.Client],
        store: str | None = None,
        outcome: str | None = None,
        products: str | None = None,
        quantity: str | None = None,
        text: str | None = None,
    ) -> None:
        clean_text = text.strip() if text and text.strip() else None
        clean_quantity = quantity.strip() if quantity and quantity.strip() else None
        log_command_invocation(
            interaction,
            "report",
            store=store,
            outcome=outcome,
            products=products,
            has_quantity=clean_quantity is not None,
            has_text=clean_text is not None,
        )
        await interaction.response.defer(ephemeral=True, thinking=True)

        if store is not None and outcome is not None:
            await self._submit_structured(
                interaction,
                store=store,
                outcome=outcome,
                products=products,
                quantity=clean_quantity,
                text=clean_text,
            )
            return

        if (
            store is None
            and outcome is None
            and products is None
            and clean_quantity is None
            and clean_text is not None
        ):
            await self._submit_free_text(interaction, clean_text)
            return

        await send_ephemeral(interaction, USAGE_MESSAGE)

    async def _submit_structured(
        self,
        interaction: discord.Interaction[discord.Client],
        *,
        store: str,
        outcome: str,
        products: str | None,
        quantity: str | None,
        text: str | None,
    ) -> None:
        try:
            store_id = parse_store_id(store)
            outcome_value = parse_outcome(outcome)
            category = parse_product(products) if products is not None else ProductCategory.OTHER
            receipt = await asyncio.to_thread(
                self.bot.report_service.submit_report,
                reporter_id=interaction.user.id,
                store_id=store_id,
                outcome=outcome_value,
                product_category=category,
                quantity_note=quantity,
                raw_text=text,
                report_source=ReportSource.DROPDOWN,
            )
        except (CommandInputError, ServiceError) as exc:
            await send_ephemeral(interaction, exc.user_message)
            return
        except Exception:
            logger.exception("report_command_failed")
            await send_ephemeral(
                interaction,
                "Something went wrong while saving that report. Please try again.",
            )
            return

        announced_publicly = await self.bot.report_notifier.announce(receipt)
        await send_ephemeral(
            interaction,
            format_report_receipt(receipt, announced_publicly=announced_publicly),
        )

    async def _submit_free_text(
        self,
        interaction: discord.Interaction[discord.Client],
        text: str,
    ) -> None:
        parser = self.bot.report_parser if self.bot.report_parser_enabled else None
        if parser is None:
            await send_ephemeral(interaction, FREE_TEXT_DISABLED_MESSAGE)
            return

        try:
            stores = await asyncio.to_thread(self.bot.store_service.list_active)
            parsed = await asyncio.to_thread(parser.parse, text, stores)
        except Exception:
            logger.exception("report_parser_failed")
            await send_ephemeral(
                interaction,
                "Free-text parsing failed. Use store and outcome instead.",
            )
            return

        if parsed.needs_clarification:
            await send_ephemeral(interaction, parsed.needs_clarification)
            return
        if parsed.store_id is None or parsed.outcome is None:
            await send_ephemeral(interaction, USAGE_MESSAGE)
            return

        store_name = next(
            (store.name for store in stores if store.id == parsed.store_id),
            None,
        )
        if store_name is None:
            await send_ephemeral(
                interaction,
                "I could not match that store. Use the autocomplete instead.",
            )
            return

        view = ConfirmReportView(
            report_service=self.bot.report_service,
            parsed=parsed,
            raw_text=text,
            reporter_id=interaction.user.id,
            notifier=self.bot.report_notifier,
        )
        await interaction.followup.send(
            format_parsed_report(parsed, store_name),
            view=view,
            ephemeral=True,
        )

    @app_commands.command(
        name="recent",
        description="Show the latest reports for a store.",
    )
    @app_commands.describe(
        store="Store from the autocomplete list",
        product="Optionally filter by product category",
    )
    @app_commands.choices(product=PRODUCT_CHOICES)
    @app_commands.autocomplete(store=store_autocomplete)
    async def recent(
        self,
        interaction: discord.Interaction[discord.Client],
        store: str,
        product: str | None = None,
    ) -> None:
        log_command_invocation(interaction, "recent", store=store, product=product)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            store_id = parse_store_id(store)
            category = parse_product(product) if product is not None else None
            reports = await asyncio.to_thread(
                self.bot.report_service.list_recent,
                store_id=store_id,
                product_category=category,
            )
        except (CommandInputError, ServiceError) as exc:
            await send_ephemeral(interaction, exc.user_message)
            return
        except Exception:
            logger.exception("recent_command_failed")
            await send_ephemeral(
                interaction,
                "Something went wrong while loading recent reports. Please try again.",
            )
            return
        await send_ephemeral(interaction, format_recent(reports))

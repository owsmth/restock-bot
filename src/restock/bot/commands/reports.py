from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.common import (
    PRODUCT_CHOICES,
    CommandInputError,
    autocomplete_stores,
    log_command_invocation,
    parse_product,
    parse_store_id,
    send_ephemeral,
)
from restock.bot.formatting import format_recent, format_report_receipt
from restock.services.errors import ServiceError

if TYPE_CHECKING:
    from restock.bot.client import RestockBot

logger = structlog.get_logger(__name__)


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
        description="Report whether a Pokemon TCG product is in stock.",
    )
    @app_commands.describe(
        store="Store from the autocomplete list",
        product="Pokemon TCG product category",
        in_stock="True if product was on the shelf, false if empty",
        minutes_ago="Minutes before now when you observed the shelf (max 2880)",
        note="Optional detail, up to 280 characters",
    )
    @app_commands.choices(product=PRODUCT_CHOICES)
    @app_commands.autocomplete(store=store_autocomplete)
    async def report(
        self,
        interaction: discord.Interaction[discord.Client],
        store: str,
        product: str,
        in_stock: bool,
        minutes_ago: app_commands.Range[int, 0, 2_880] = 0,
        note: str | None = None,
    ) -> None:
        log_command_invocation(
            interaction,
            "report",
            store=store,
            product=product,
            in_stock=in_stock,
            minutes_ago=minutes_ago,
        )
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            store_id = parse_store_id(store)
            category = parse_product(product)
            receipt = await asyncio.to_thread(
                self.bot.report_service.submit_report,
                reporter_id=interaction.user.id,
                store_id=store_id,
                product_category=category,
                in_stock=in_stock,
                minutes_ago=minutes_ago,
                note=note,
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

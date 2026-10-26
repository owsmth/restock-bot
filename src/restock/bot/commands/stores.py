from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.common import (
    RETAILER_CHOICES,
    CommandInputError,
    log_command_invocation,
    parse_retailer,
    send_ephemeral,
)
from restock.bot.formatting import format_store
from restock.services.errors import ServiceError

if TYPE_CHECKING:
    from restock.bot.client import RestockBot

logger = structlog.get_logger(__name__)


class StoreCommands(commands.Cog):
    def __init__(self, bot: RestockBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stores",
        description="List active stores and their IDs.",
    )
    @app_commands.describe(retailer="Optionally filter by retailer")
    @app_commands.choices(retailer=RETAILER_CHOICES)
    async def stores(
        self,
        interaction: discord.Interaction[discord.Client],
        retailer: str | None = None,
    ) -> None:
        log_command_invocation(interaction, "stores", retailer=retailer)
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            parsed_retailer = parse_retailer(retailer)
            stores = await asyncio.to_thread(
                self.bot.store_service.list_active,
                parsed_retailer,
            )
        except (CommandInputError, ServiceError) as exc:
            await send_ephemeral(interaction, exc.user_message)
            return
        except Exception:
            logger.exception("stores_command_failed")
            await send_ephemeral(
                interaction,
                "Something went wrong while loading stores. Please try again.",
            )
            return
        await send_ephemeral(interaction, format_store(stores))

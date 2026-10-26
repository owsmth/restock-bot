from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.common import (
    CommandInputError,
    autocomplete_stores,
    log_admin_action,
    parse_store_id,
    send_ephemeral,
)
from restock.services.errors import ServiceError

if TYPE_CHECKING:
    from restock.bot.client import RestockBot

logger = structlog.get_logger(__name__)


class AdminCommands(commands.Cog):
    def __init__(self, bot: RestockBot) -> None:
        self.bot = bot

    async def store_autocomplete(
        self,
        interaction: discord.Interaction[discord.Client],
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await autocomplete_stores(
            self.bot.store_service,
            current,
            include_inactive=True,
        )

    @app_commands.command(
        name="admin_delete_report",
        description="Delete a report by its ID (Manage Server only).",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.rename(report_id="id")
    @app_commands.describe(report_id="Report ID shown in the private report receipt")
    async def admin_delete_report(
        self,
        interaction: discord.Interaction[discord.Client],
        report_id: app_commands.Range[int, 1],
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            deleted = await asyncio.to_thread(
                self.bot.report_service.delete_report,
                report_id,
            )
        except ServiceError as exc:
            log_admin_action(
                "delete_report",
                "rejected",
                report_id=report_id,
                error_type=type(exc).__name__,
            )
            await send_ephemeral(interaction, exc.user_message)
            return
        except Exception:
            logger.exception(
                "admin_action_failed",
                admin_action="delete_report",
                report_id=report_id,
            )
            await send_ephemeral(
                interaction,
                "Something went wrong while deleting that report. Please try again.",
            )
            return

        log_admin_action(
            "delete_report",
            "success",
            report_id=deleted.observation_id,
            store_id=deleted.store_id,
        )
        await send_ephemeral(
            interaction,
            f"Deleted report `#{deleted.observation_id}` for **{deleted.store_name}**.",
        )

    @app_commands.command(
        name="admin_set_store_active",
        description="Activate or deactivate a store (Manage Server only).",
    )
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        store="Store from the autocomplete list",
        active="True to accept reports, false to hide it from /stores and /report",
    )
    @app_commands.autocomplete(store=store_autocomplete)
    async def admin_set_store_active(
        self,
        interaction: discord.Interaction[discord.Client],
        store: str,
        active: bool,
    ) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            store_id = parse_store_id(store)
            updated = await asyncio.to_thread(
                self.bot.store_service.set_active,
                store_id,
                active,
            )
        except (CommandInputError, ServiceError) as exc:
            log_admin_action(
                "set_store_active",
                "rejected",
                store_id=store,
                active=active,
                error_type=type(exc).__name__,
            )
            await send_ephemeral(interaction, exc.user_message)
            return
        except Exception:
            logger.exception(
                "admin_action_failed",
                admin_action="set_store_active",
                store_id=store,
                active=active,
            )
            await send_ephemeral(
                interaction,
                "Something went wrong while updating that store. Please try again.",
            )
            return

        state = "active" if updated.active else "inactive"
        log_admin_action(
            "set_store_active",
            "success",
            store_id=updated.id,
            active=updated.active,
        )
        await send_ephemeral(
            interaction,
            f"Store `#{updated.id}` **{updated.name}** is now {state}.",
        )

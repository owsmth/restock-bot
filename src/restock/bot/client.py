from __future__ import annotations

import discord
import structlog
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.admin import AdminCommands
from restock.bot.commands.help import HelpCommands
from restock.bot.commands.reports import ReportCommands
from restock.bot.commands.stores import StoreCommands
from restock.bot.notifier import ReportNotifier
from restock.services.reports import ReportService
from restock.services.stores import StoreService

logger = structlog.get_logger(__name__)


class RestockBot(commands.Bot):
    def __init__(
        self,
        *,
        guild_id: int,
        report_service: ReportService,
        store_service: StoreService,
        local_restock_channel_id: int | None = None,
    ) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            allowed_mentions=discord.AllowedMentions.none(),
            tree_cls=RestockCommandTree,
        )
        self.guild_id = guild_id
        self.report_service = report_service
        self.store_service = store_service
        self.local_restock_channel_id = local_restock_channel_id
        self.report_notifier = ReportNotifier(self, local_restock_channel_id)

    async def setup_hook(self) -> None:
        await self.add_cog(ReportCommands(self))
        await self.add_cog(StoreCommands(self))
        await self.add_cog(AdminCommands(self))
        await self.add_cog(HelpCommands(self))
        guild = discord.Object(id=self.guild_id)
        # Commands are defined globally in code, but synced only to the test guild.
        # discord.py syncs guild-specific commands when ``guild`` is provided.
        self.tree.copy_global_to(guild=guild)
        synced = await self.tree.sync(guild=guild)
        logger.info(
            "commands_synced",
            guild_id=self.guild_id,
            command_count=len(synced),
        )

    async def on_ready(self) -> None:
        if self.user is not None:
            logger.info(
                "bot_ready",
                user_id=self.user.id,
                guild_count=len(self.guilds),
            )


class RestockCommandTree(app_commands.CommandTree[RestockBot]):
    async def on_error(
        self,
        interaction: discord.Interaction[RestockBot],
        error: app_commands.AppCommandError,
        /,
    ) -> None:
        logger.error(
            "command_failed",
            command=getattr(interaction.command, "name", None),
            guild_id=interaction.guild_id,
            channel_id=interaction.channel_id,
            error_type=type(error).__name__,
            exc_info=error,
        )
        message = "Something went wrong while handling that command. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            logger.exception("command_error_reply_failed")

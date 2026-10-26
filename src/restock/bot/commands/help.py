from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from restock.bot.commands.common import log_command_invocation, send_ephemeral
from restock.bot.formatting import format_help

if TYPE_CHECKING:
    from restock.bot.client import RestockBot


class HelpCommands(commands.Cog):
    def __init__(self, bot: RestockBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="help",
        description="Explain the restock reporting commands.",
    )
    async def help(self, interaction: discord.Interaction[discord.Client]) -> None:
        log_command_invocation(interaction, "help")
        await send_ephemeral(interaction, format_help())

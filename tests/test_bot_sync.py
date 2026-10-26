from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import discord
import pytest

from restock.bot.client import RestockBot

GUILD_ID = 123456789012345678


def test_setup_hook_copies_global_commands_into_guild_sync(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = RestockBot(
        guild_id=GUILD_ID,
        report_service=MagicMock(),
        store_service=MagicMock(),
    )
    synced_guild: int | None = None
    synced_commands: list[str] = []

    async def fake_sync(*, guild: discord.abc.Snowflake) -> list[discord.app_commands.AppCommand]:
        nonlocal synced_guild, synced_commands
        synced_guild = guild.id
        synced_commands = sorted(command.name for command in bot.tree.get_commands(guild=guild))
        return []

    monkeypatch.setattr(bot.tree, "sync", fake_sync)
    asyncio.run(bot.setup_hook())

    assert synced_guild == GUILD_ID
    assert synced_commands == [
        "admin_delete_report",
        "admin_set_store_active",
        "help",
        "recent",
        "report",
        "stores",
    ]

    commands = {
        command.name: command
        for command in bot.tree.get_commands(guild=discord.Object(id=GUILD_ID))
        if isinstance(command, discord.app_commands.Command)
    }
    delete_command = commands["admin_delete_report"]
    assert delete_command.default_permissions == discord.Permissions(manage_guild=True)
    assert [parameter.name for parameter in delete_command.parameters] == ["report_id"]
    assert [parameter.display_name for parameter in delete_command.parameters] == ["id"]
    set_active_command = commands["admin_set_store_active"]
    assert set_active_command.default_permissions == discord.Permissions(manage_guild=True)
    assert [parameter.name for parameter in set_active_command.parameters] == [
        "store",
        "active",
    ]
    assert commands["help"].default_permissions is None

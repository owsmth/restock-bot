from __future__ import annotations

import asyncio
import sys

import discord
from pydantic import ValidationError
from sqlalchemy import Engine

from restock.bot.client import RestockBot
from restock.config import Settings, get_settings
from restock.db.engine import create_db_engine
from restock.db.session import create_session_factory
from restock.logging import configure_logging
from restock.services.reports import ReportService
from restock.services.stores import StoreService


def build_bot(settings: Settings) -> tuple[RestockBot, Engine]:
    if settings.discord_token is None:
        raise ValueError("DISCORD_TOKEN is required to run the bot")
    if settings.guild_id is None:
        raise ValueError("GUILD_ID is required to sync commands to a test guild")

    engine = create_db_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    bot = RestockBot(
        guild_id=settings.guild_id,
        report_service=ReportService(
            session_factory,
            reporter_hash_salt=settings.reporter_hash_salt.get_secret_value(),
        ),
        store_service=StoreService(session_factory),
        local_restock_channel_id=settings.local_restock_channel_id,
    )
    return bot, engine


async def run(bot: RestockBot, token: str) -> None:
    async with bot:
        await bot.start(token)


def main() -> int:
    try:
        settings = get_settings()
    except ValidationError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    configure_logging(settings.log_level)
    try:
        bot, engine = build_bot(settings)
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    token = settings.discord_token
    if token is None:
        engine.dispose()
        return 1
    try:
        asyncio.run(run(bot, token.get_secret_value()))
    except KeyboardInterrupt:
        print("Bot stopped.", file=sys.stderr)
    except discord.LoginFailure:
        print("Discord rejected DISCORD_TOKEN. Check the value in .env.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

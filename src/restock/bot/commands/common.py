from __future__ import annotations

import asyncio

import discord
import structlog
from discord import app_commands

from restock.bot.formatting import (
    PRODUCT_LABELS,
    RETAILER_LABELS,
    format_store_autocomplete,
)
from restock.db.models import ProductCategory, Retailer
from restock.services.stores import StoreService, StoreSummary

logger = structlog.get_logger(__name__)

PRODUCT_CHOICES = [
    app_commands.Choice(name=label, value=category.value)
    for category, label in PRODUCT_LABELS.items()
]
RETAILER_CHOICES = [
    app_commands.Choice(name=label, value=retailer.value)
    for retailer, label in RETAILER_LABELS.items()
]


class CommandInputError(ValueError):
    def __init__(self, user_message: str) -> None:
        super().__init__(user_message)
        self.user_message = user_message


def parse_store_id(value: str) -> int:
    try:
        store_id = int(value)
    except ValueError as exc:
        raise CommandInputError("Choose a store from the autocomplete list.") from exc
    if store_id <= 0:
        raise CommandInputError("Choose a store from the autocomplete list.")
    return store_id


def parse_product(value: str) -> ProductCategory:
    try:
        return ProductCategory(value)
    except ValueError as exc:
        raise CommandInputError("Choose a product from the command options.") from exc


def parse_retailer(value: str | None) -> Retailer | None:
    if value is None:
        return None
    try:
        return Retailer(value)
    except ValueError as exc:
        raise CommandInputError("Choose a retailer from the command options.") from exc


def log_command_invocation(
    interaction: discord.Interaction[discord.Client],
    command: str,
    **fields: object,
) -> None:
    logger.info(
        "command_invoked",
        command=command,
        guild_id=interaction.guild_id,
        channel_id=interaction.channel_id,
        **fields,
    )


def log_admin_action(action: str, outcome: str, **fields: object) -> None:
    # Deliberately excludes Discord actor, guild, and channel IDs.
    logger.info("admin_action", admin_action=action, outcome=outcome, **fields)


async def autocomplete_stores(
    service: StoreService,
    current: str,
    *,
    include_inactive: bool = False,
) -> list[app_commands.Choice[str]]:
    search = service.search_all if include_inactive else service.search_active
    try:
        async with asyncio.timeout(2.5):
            stores = await asyncio.to_thread(search, current, limit=25)
    except TimeoutError:
        logger.warning("store_autocomplete_timeout")
        return []
    except Exception:
        logger.exception("store_autocomplete_failed")
        return []
    return [
        app_commands.Choice(
            name=_autocomplete_choice_name(store, include_inactive=include_inactive),
            value=str(store.id),
        )
        for store in stores
    ]


def _autocomplete_choice_name(store: StoreSummary, *, include_inactive: bool) -> str:
    label = format_store_autocomplete(store)
    if include_inactive and not store.active:
        return f"{label} (inactive)"[:100]
    return label


async def send_ephemeral(
    interaction: discord.Interaction[discord.Client],
    content: str,
) -> None:
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)

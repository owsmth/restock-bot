from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord

from restock.bot.notifier import ReportNotifier, build_report_announcement
from restock.db.models import ProductCategory
from restock.services.reports import ReportReceipt

OBSERVED_AT = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)


def _receipt(*, in_stock: bool = True) -> ReportReceipt:
    return ReportReceipt(
        observation_id=42,
        store_name="Target - Colonial Blvd",
        store_city="Fort Myers",
        store_timezone="America/New_York",
        product_category=ProductCategory.ETB,
        in_stock=in_stock,
        observed_at=OBSERVED_AT,
        reported_at=OBSERVED_AT,
    )


def test_announcement_embed_has_required_content_and_distinct_stock_styles() -> None:
    in_stock = build_report_announcement(_receipt(in_stock=True))
    out_of_stock = build_report_announcement(_receipt(in_stock=False))

    assert in_stock.title is not None
    assert "In stock" in in_stock.title
    assert "Target - Colonial Blvd" in in_stock.title
    assert in_stock.description is not None
    assert "Fort Myers" in in_stock.description
    assert "Elite Trainer Box (ETB)" in in_stock.description
    assert in_stock.color == discord.Color.green()
    assert in_stock.fields[0].name == "Observed"
    assert in_stock.fields[0].value == f"<t:{int(OBSERVED_AT.timestamp())}:R>"

    assert out_of_stock.title is not None
    assert "Out of stock" in out_of_stock.title
    assert out_of_stock.color == discord.Color.red()


def test_announcement_posts_with_mentions_disabled() -> None:
    channel = MagicMock()
    channel.send = AsyncMock()
    bot = MagicMock()
    bot.get_channel.return_value = channel
    notifier = ReportNotifier(bot, 123456789)

    announced = asyncio.run(notifier.announce(_receipt()))

    assert announced is True
    channel.send.assert_awaited_once()
    call = channel.send.await_args
    assert call is not None
    kwargs = call.kwargs
    mentions = kwargs["allowed_mentions"]
    assert isinstance(mentions, discord.AllowedMentions)
    assert mentions.everyone is False
    assert mentions.users is False
    assert mentions.roles is False
    assert mentions.replied_user is False
    assert isinstance(kwargs["embed"], discord.Embed)


def test_announcement_is_skipped_without_a_channel() -> None:
    bot = MagicMock()
    notifier = ReportNotifier(bot, None)

    assert asyncio.run(notifier.announce(_receipt())) is False
    bot.get_channel.assert_not_called()


def test_announcement_failure_returns_false_instead_of_raising() -> None:
    bot = MagicMock()
    bot.get_channel.return_value = None
    bot.fetch_channel = AsyncMock(side_effect=RuntimeError("Discord unavailable"))
    notifier = ReportNotifier(bot, 123456789)

    assert asyncio.run(notifier.announce(_receipt())) is False

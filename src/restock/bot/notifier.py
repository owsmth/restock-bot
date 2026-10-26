from __future__ import annotations

from typing import cast

import discord
import structlog

from restock.bot.formatting import product_label
from restock.services.reports import ReportReceipt

logger = structlog.get_logger(__name__)


def build_report_announcement(receipt: ReportReceipt) -> discord.Embed:
    if receipt.in_stock:
        stock = "✅ In stock"
        color = discord.Color.green()
    else:
        stock = "❌ Out of stock"
        color = discord.Color.red()

    embed = discord.Embed(
        title=f"{stock} · {receipt.store_name}"[:256],
        description=f"{receipt.store_city} · {product_label(receipt.product_category)}",
        color=color,
    )
    timestamp = int(receipt.observed_at.timestamp())
    embed.add_field(name="Observed", value=f"<t:{timestamp}:R>", inline=True)
    embed.set_footer(text="Unverified community report")
    return embed


class ReportNotifier:
    def __init__(self, bot: discord.Client, channel_id: int | None) -> None:
        self._bot = bot
        self._channel_id = channel_id

    async def announce(self, receipt: ReportReceipt) -> bool:
        if self._channel_id is None:
            return False
        try:
            channel = self._bot.get_channel(self._channel_id)
            if channel is None:
                channel = await self._bot.fetch_channel(self._channel_id)
            messageable = cast(discord.abc.Messageable, channel)
            await messageable.send(
                embed=build_report_announcement(receipt),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            logger.warning(
                "report_announcement_failed",
                observation_id=receipt.observation_id,
                channel_id=self._channel_id,
                exc_info=True,
            )
            return False

        logger.info(
            "report_announced",
            observation_id=receipt.observation_id,
            channel_id=self._channel_id,
        )
        return True

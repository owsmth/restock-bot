from __future__ import annotations

from typing import cast

import discord
import structlog

from restock.bot.formatting import outcome_label, product_label
from restock.db.models import ReportOutcome
from restock.services.reports import ReportReceipt

logger = structlog.get_logger(__name__)

_OUTCOME_COLORS = {
    ReportOutcome.JUST_DROPPED: discord.Color.orange(),
    ReportOutcome.IN_STOCK: discord.Color.green(),
    ReportOutcome.SOLD_OUT: discord.Color.red(),
    ReportOutcome.NOTHING_HERE: discord.Color(0x607D8B),
}


def build_report_announcement(receipt: ReportReceipt) -> discord.Embed:
    label = outcome_label(receipt.outcome)
    embed = discord.Embed(
        title=f"{label} · {receipt.store_name}"[:256],
        description=f"{receipt.store_city} · {product_label(receipt.product_category)}",
        color=_OUTCOME_COLORS[receipt.outcome],
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

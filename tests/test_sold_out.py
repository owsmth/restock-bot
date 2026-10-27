from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from restock.db.models import ReportOutcome
from restock.repositories.observations import OutcomeObservation
from restock.services.reports import time_to_sold_out

STORE_ID = 7


def observation(
    outcome: ReportOutcome,
    *,
    day: int,
    hour: int,
    minute: int = 0,
) -> OutcomeObservation:
    return OutcomeObservation(
        store_id=STORE_ID,
        outcome=outcome,
        observed_at=datetime(2026, 10, day, hour, minute, tzinfo=UTC),
    )


def test_time_to_sold_out_uses_earliest_drop_and_later_sale() -> None:
    rows = [
        observation(ReportOutcome.JUST_DROPPED, day=26, hour=14),
        observation(ReportOutcome.JUST_DROPPED, day=26, hour=14, minute=10),
        observation(ReportOutcome.SOLD_OUT, day=26, hour=14, minute=30),
        observation(ReportOutcome.SOLD_OUT, day=26, hour=14, minute=20),
    ]

    assert time_to_sold_out(rows, STORE_ID, date(2026, 10, 26)) == timedelta(minutes=20)


def test_time_to_sold_out_requires_a_drop_and_a_later_sale() -> None:
    drop = observation(ReportOutcome.JUST_DROPPED, day=26, hour=14)
    sale = observation(ReportOutcome.SOLD_OUT, day=26, hour=14, minute=30)

    assert time_to_sold_out([sale], STORE_ID, date(2026, 10, 26)) is None
    assert time_to_sold_out([drop], STORE_ID, date(2026, 10, 26)) is None
    assert (
        time_to_sold_out(
            [
                observation(ReportOutcome.SOLD_OUT, day=26, hour=13),
                drop,
            ],
            STORE_ID,
            date(2026, 10, 26),
        )
        is None
    )


def test_time_to_sold_out_ignores_other_stores_and_other_days() -> None:
    rows = [
        observation(ReportOutcome.JUST_DROPPED, day=25, hour=14),
        observation(ReportOutcome.SOLD_OUT, day=25, hour=15),
        OutcomeObservation(
            store_id=STORE_ID + 1,
            outcome=ReportOutcome.JUST_DROPPED,
            observed_at=datetime(2026, 10, 26, 14, tzinfo=UTC),
        ),
        OutcomeObservation(
            store_id=STORE_ID + 1,
            outcome=ReportOutcome.SOLD_OUT,
            observed_at=datetime(2026, 10, 26, 15, tzinfo=UTC),
        ),
    ]

    assert time_to_sold_out(rows, STORE_ID, date(2026, 10, 26)) is None


def test_time_to_sold_out_uses_the_new_york_local_day_at_midnight() -> None:
    # 03:50 UTC is 23:50 EDT on October 26; 04:10 UTC is 00:10 EDT on October 27.
    drop_before_midnight = observation(ReportOutcome.JUST_DROPPED, day=27, hour=3, minute=50)
    sale_after_midnight = observation(ReportOutcome.SOLD_OUT, day=27, hour=4, minute=10)
    same_day_drop = observation(ReportOutcome.JUST_DROPPED, day=26, hour=4)
    same_day_sale = observation(ReportOutcome.SOLD_OUT, day=26, hour=5)

    assert (
        time_to_sold_out(
            [drop_before_midnight, sale_after_midnight],
            STORE_ID,
            date(2026, 10, 26),
        )
        is None
    )
    assert (
        time_to_sold_out(
            [drop_before_midnight, sale_after_midnight],
            STORE_ID,
            date(2026, 10, 27),
        )
        is None
    )
    assert time_to_sold_out(
        [same_day_drop, same_day_sale],
        STORE_ID,
        date(2026, 10, 26),
    ) == timedelta(hours=1)

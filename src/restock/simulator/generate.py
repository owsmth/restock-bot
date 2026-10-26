from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from restock.db.models import ProductCategory
from restock.simulator.patterns import (
    PLANTED_PATTERNS,
    NoiseProfile,
    PatternKind,
    RestockPattern,
)

_TRUE_NOTE = "SIMULATOR: simulated restock sighting"
_FALSE_NEGATIVE_NOTE = "SIMULATOR: simulated empty shelf during restock window"
_BACKGROUND_NEGATIVE_NOTE = "SIMULATOR: simulated empty shelf"
DEFAULT_NOISE = NoiseProfile()


@dataclass(frozen=True, slots=True)
class SimulationStore:
    id: int
    name: str
    timezone: str


@dataclass(frozen=True, slots=True)
class SimulatedRestock:
    store_name: str
    product_category: ProductCategory
    occurred_at: datetime
    window_start: datetime
    window_end: datetime


@dataclass(frozen=True, slots=True)
class SimulatedObservation:
    store_name: str
    product_category: ProductCategory
    in_stock: bool
    observed_at: datetime
    reported_at: datetime
    reporter_hash: str
    quantity_estimate: int | None
    notes: str


@dataclass(frozen=True, slots=True)
class SimulationResult:
    restocks: tuple[SimulatedRestock, ...]
    observations: tuple[SimulatedObservation, ...]
    starts_on: date
    ends_on: date


def simulate(
    *,
    stores: Sequence[SimulationStore],
    starts_on: date,
    weeks: int,
    seed: int,
    patterns: Sequence[RestockPattern] = PLANTED_PATTERNS,
    noise: NoiseProfile = DEFAULT_NOISE,
) -> SimulationResult:
    if weeks < 1:
        raise ValueError("weeks must be at least 1")
    if len({store.name for store in stores}) != len(stores):
        raise ValueError("simulation store names must be unique")

    store_by_name = {store.name: store for store in stores}
    missing = sorted({pattern.store_name for pattern in patterns} - set(store_by_name))
    if missing:
        raise ValueError("no active seeded store matches simulator patterns: " + ", ".join(missing))

    rng = random.Random(seed)
    restocks: list[SimulatedRestock] = []
    observations: list[SimulatedObservation] = []

    for pattern in patterns:
        store = store_by_name[pattern.store_name]
        timezone = ZoneInfo(store.timezone)
        for day_offset in range(weeks * 7):
            local_day = starts_on + timedelta(days=day_offset)
            if not _restock_day(pattern, local_day, rng):
                continue

            window_start = datetime.combine(
                local_day,
                time(hour=pattern.start_hour),
                tzinfo=timezone,
            ).astimezone(UTC)
            window_end = datetime.combine(
                local_day,
                time(hour=pattern.end_hour),
                tzinfo=timezone,
            ).astimezone(UTC)
            occurred_at = _random_instant(rng, window_start, window_end)
            restock = SimulatedRestock(
                store_name=store.name,
                product_category=pattern.product_category,
                occurred_at=occurred_at,
                window_start=window_start,
                window_end=window_end,
            )
            restocks.append(restock)

            if rng.random() < noise.report_probability:
                observations.append(_true_observation(rng, restock, noise))
                if rng.random() < noise.additional_report_probability:
                    observations.append(_true_observation(rng, restock, noise))

            if rng.random() < noise.false_negative_probability:
                observations.append(
                    _negative_observation(
                        rng,
                        store_name=restock.store_name,
                        product_category=restock.product_category,
                        window_start=restock.window_start,
                        window_end=restock.window_end,
                        noise=noise,
                        notes=_FALSE_NEGATIVE_NOTE,
                    )
                )

            if rng.random() < noise.background_negative_probability:
                background_start = datetime.combine(
                    local_day,
                    time(hour=noise.background_start_hour),
                    tzinfo=timezone,
                ).astimezone(UTC)
                background_end = datetime.combine(
                    local_day,
                    time(hour=noise.background_end_hour),
                    tzinfo=timezone,
                ).astimezone(UTC)
                observations.append(
                    _negative_observation(
                        rng,
                        store_name=restock.store_name,
                        product_category=restock.product_category,
                        window_start=background_start,
                        window_end=background_end,
                        noise=noise,
                        notes=_BACKGROUND_NEGATIVE_NOTE,
                    )
                )

    return SimulationResult(
        restocks=tuple(restocks),
        observations=tuple(observations),
        starts_on=starts_on,
        ends_on=starts_on + timedelta(weeks=weeks),
    )


def _restock_day(pattern: RestockPattern, day: date, rng: random.Random) -> bool:
    if pattern.kind is PatternKind.WEEKLY:
        return day.weekday() in pattern.weekdays
    return rng.random() < pattern.daily_probability


def _random_instant(
    rng: random.Random,
    window_start: datetime,
    window_end: datetime,
) -> datetime:
    available_seconds = int((window_end - window_start).total_seconds())
    return window_start + timedelta(seconds=rng.randrange(available_seconds))


def _observation_time(
    rng: random.Random,
    observed_after: datetime,
    window_end: datetime,
) -> datetime:
    latest = window_end - timedelta(seconds=1)
    candidate = observed_after + timedelta(minutes=rng.randint(0, 30))
    return min(candidate, latest)


def _reporting_lag(rng: random.Random, noise: NoiseProfile) -> timedelta:
    minutes = rng.randint(
        noise.min_reporting_lag_minutes,
        noise.max_reporting_lag_minutes,
    )
    seconds = rng.randint(0, 59)
    return timedelta(minutes=minutes, seconds=seconds)


def _synthetic_reporter_hash(rng: random.Random) -> str:
    return f"{rng.getrandbits(256):064x}"


def _true_observation(
    rng: random.Random,
    restock: SimulatedRestock,
    noise: NoiseProfile,
) -> SimulatedObservation:
    observed_at = _observation_time(rng, restock.occurred_at, restock.window_end)
    reported_at = observed_at + _reporting_lag(rng, noise)
    return SimulatedObservation(
        store_name=restock.store_name,
        product_category=restock.product_category,
        in_stock=True,
        observed_at=observed_at,
        reported_at=reported_at,
        reporter_hash=_synthetic_reporter_hash(rng),
        quantity_estimate=rng.randint(1, 12),
        notes=_TRUE_NOTE,
    )


def _negative_observation(
    rng: random.Random,
    *,
    store_name: str,
    product_category: ProductCategory,
    window_start: datetime,
    window_end: datetime,
    noise: NoiseProfile,
    notes: str,
) -> SimulatedObservation:
    observed_at = _random_instant(rng, window_start, window_end)
    reported_at = observed_at + _reporting_lag(rng, noise)
    return SimulatedObservation(
        store_name=store_name,
        product_category=product_category,
        in_stock=False,
        observed_at=observed_at,
        reported_at=reported_at,
        reporter_hash=_synthetic_reporter_hash(rng),
        quantity_estimate=None,
        notes=notes,
    )

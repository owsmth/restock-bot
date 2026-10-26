from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from restock.db.models import ProductCategory


class PatternKind(StrEnum):
    WEEKLY = "weekly"
    DAILY_RANDOM = "daily_random"


@dataclass(frozen=True, slots=True)
class RestockPattern:
    store_name: str
    product_category: ProductCategory
    kind: PatternKind
    start_hour: int
    end_hour: int
    weekdays: tuple[int, ...] = ()
    daily_probability: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.start_hour < self.end_hour <= 24:
            raise ValueError("pattern must satisfy 0 <= start_hour < end_hour <= 24")
        if self.kind is PatternKind.WEEKLY:
            if not self.weekdays:
                raise ValueError("weekly patterns require at least one weekday")
            if any(weekday < 0 or weekday > 6 for weekday in self.weekdays):
                raise ValueError("weekdays must be between 0 (Monday) and 6 (Sunday)")
            if self.daily_probability != 0.0:
                raise ValueError("weekly patterns cannot set daily_probability")
        else:
            if self.weekdays:
                raise ValueError("random daily patterns cannot set weekdays")
            if not 0 <= self.daily_probability <= 1:
                raise ValueError("daily_probability must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class NoiseProfile:
    report_probability: float = 0.8
    additional_report_probability: float = 0.3
    false_negative_probability: float = 0.15
    background_negative_probability: float = 0.08
    min_reporting_lag_minutes: int = 5
    max_reporting_lag_minutes: int = 180
    background_start_hour: int = 8
    background_end_hour: int = 21

    def __post_init__(self) -> None:
        probabilities = (
            self.report_probability,
            self.additional_report_probability,
            self.false_negative_probability,
            self.background_negative_probability,
        )
        if any(not 0 <= probability <= 1 for probability in probabilities):
            raise ValueError("noise probabilities must be between 0 and 1")
        if self.min_reporting_lag_minutes < 0:
            raise ValueError("minimum reporting lag cannot be negative")
        if self.max_reporting_lag_minutes < self.min_reporting_lag_minutes:
            raise ValueError("maximum reporting lag must be at least the minimum")
        if not 0 <= self.background_start_hour < self.background_end_hour <= 24:
            raise ValueError("background hours must be a valid local-time window")


# Monday=0. These names intentionally match data/stores_seed.csv.
PLANTED_PATTERNS: tuple[RestockPattern, ...] = (
    RestockPattern(
        store_name="EXAMPLE Target Cape Coral",
        product_category=ProductCategory.ETB,
        kind=PatternKind.WEEKLY,
        weekdays=(1, 4),
        start_hour=8,
        end_hour=11,
    ),
    RestockPattern(
        store_name="EXAMPLE Walmart Fort Myers",
        product_category=ProductCategory.ETB,
        kind=PatternKind.DAILY_RANDOM,
        start_hour=9,
        end_hour=20,
        daily_probability=0.10,
    ),
    RestockPattern(
        store_name="EXAMPLE Costco Naples",
        product_category=ProductCategory.BOOSTER_BOX,
        kind=PatternKind.WEEKLY,
        weekdays=(3,),
        start_hour=13,
        end_hour=17,
    ),
    RestockPattern(
        store_name="EXAMPLE Best Buy Fort Myers",
        product_category=ProductCategory.ETB,
        kind=PatternKind.WEEKLY,
        weekdays=(5,),
        start_hour=10,
        end_hour=13,
    ),
    RestockPattern(
        store_name="EXAMPLE Walgreens Cape Coral",
        product_category=ProductCategory.BLISTER,
        kind=PatternKind.DAILY_RANDOM,
        start_hour=10,
        end_hour=19,
        daily_probability=0.05,
    ),
    RestockPattern(
        store_name="EXAMPLE Sams Club Naples",
        product_category=ProductCategory.COLLECTION_BOX,
        kind=PatternKind.DAILY_RANDOM,
        start_hour=11,
        end_hour=19,
        daily_probability=0.08,
    ),
)

from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

import pytest

from restock.db.models import ProductCategory
from restock.simulator.generate import SimulationResult, SimulationStore, simulate
from restock.simulator.patterns import PLANTED_PATTERNS, NoiseProfile, PatternKind

SIMULATION_STORES = (
    SimulationStore(1, "EXAMPLE Target Cape Coral", "America/New_York"),
    SimulationStore(2, "EXAMPLE Walmart Fort Myers", "America/New_York"),
    SimulationStore(3, "EXAMPLE Costco Naples", "America/New_York"),
    SimulationStore(4, "EXAMPLE Best Buy Fort Myers", "America/New_York"),
    SimulationStore(5, "EXAMPLE Walgreens Cape Coral", "America/New_York"),
    SimulationStore(6, "EXAMPLE Sams Club Naples", "America/New_York"),
)
START_DATE = date(2025, 1, 6)  # Monday
NEW_YORK = ZoneInfo("America/New_York")


def simulate_twelve_weeks(seed: int = 42) -> SimulationResult:
    return simulate(
        stores=SIMULATION_STORES,
        starts_on=START_DATE,
        weeks=12,
        seed=seed,
    )


def test_planted_patterns_match_required_examples() -> None:
    by_store = {pattern.store_name: pattern for pattern in PLANTED_PATTERNS}
    target = by_store["EXAMPLE Target Cape Coral"]
    walmart = by_store["EXAMPLE Walmart Fort Myers"]
    costco = by_store["EXAMPLE Costco Naples"]

    assert target.kind is PatternKind.WEEKLY
    assert target.weekdays == (1, 4)
    assert (target.start_hour, target.end_hour) == (8, 11)
    assert walmart.kind is PatternKind.DAILY_RANDOM
    assert walmart.daily_probability == 0.10
    assert costco.kind is PatternKind.WEEKLY
    assert costco.weekdays == (3,)
    assert (costco.start_hour, costco.end_hour) == (13, 17)


def test_generation_is_deterministic_given_seed() -> None:
    first = simulate_twelve_weeks(seed=42)
    second = simulate_twelve_weeks(seed=42)
    different = simulate_twelve_weeks(seed=43)

    assert first == second
    assert first != different


def test_weekly_patterns_generate_events_inside_local_windows() -> None:
    result = simulate_twelve_weeks()
    target_events = [
        event for event in result.restocks if event.store_name == "EXAMPLE Target Cape Coral"
    ]
    costco_events = [
        event for event in result.restocks if event.store_name == "EXAMPLE Costco Naples"
    ]

    assert len(target_events) == 24
    assert all(event.product_category is ProductCategory.ETB for event in target_events)
    for event in target_events:
        local = event.window_start.astimezone(NEW_YORK)
        assert local.weekday() in (1, 4)
        assert local.hour == 8
        assert event.window_end.astimezone(NEW_YORK).hour == 11
        assert event.window_start <= event.occurred_at < event.window_end

    assert len(costco_events) == 12
    assert all(event.window_start.astimezone(NEW_YORK).weekday() == 3 for event in costco_events)
    assert all(event.window_start.astimezone(NEW_YORK).hour == 13 for event in costco_events)
    assert all(event.window_end.astimezone(NEW_YORK).hour == 17 for event in costco_events)


def test_daily_random_pattern_approximates_ten_percent() -> None:
    result = simulate_twelve_weeks()
    walmart_events = [
        event for event in result.restocks if event.store_name == "EXAMPLE Walmart Fort Myers"
    ]

    assert 4 <= len(walmart_events) <= 16
    assert all(9 <= event.window_start.astimezone(NEW_YORK).hour < 20 for event in walmart_events)


def test_reports_include_lag_noise_and_missed_restocks() -> None:
    result = simulate_twelve_weeks()

    assert result.observations
    assert all(
        observation.reported_at > observation.observed_at for observation in result.observations
    )
    assert any(
        (observation.reported_at - observation.observed_at).total_seconds() >= 30 * 60
        for observation in result.observations
    )
    assert all(len(observation.reporter_hash) == 64 for observation in result.observations)
    assert all(observation.notes.startswith("SIMULATOR:") for observation in result.observations)
    assert {observation.in_stock for observation in result.observations} == {True, False}

    true_observations = [observation for observation in result.observations if observation.in_stock]
    negative_observations = [
        observation for observation in result.observations if not observation.in_stock
    ]
    assert true_observations
    assert negative_observations

    missed_events = 0
    for event in result.restocks:
        matching = [
            observation
            for observation in true_observations
            if observation.store_name == event.store_name
            and observation.product_category is event.product_category
            and event.window_start <= observation.observed_at < event.window_end
        ]
        if not matching:
            missed_events += 1
    assert missed_events > 0

    false_negatives_in_window = [
        observation
        for observation in negative_observations
        if any(
            observation.store_name == event.store_name
            and observation.product_category is event.product_category
            and event.window_start <= observation.observed_at < event.window_end
            for event in result.restocks
        )
    ]
    assert false_negatives_in_window


def test_simulation_rejects_unknown_store_and_bad_weeks() -> None:
    with pytest.raises(ValueError, match="weeks"):
        simulate(stores=SIMULATION_STORES, starts_on=START_DATE, weeks=0, seed=42)

    with pytest.raises(ValueError, match="no active seeded store"):
        simulate(
            stores=SIMULATION_STORES[:1],
            starts_on=START_DATE,
            weeks=1,
            seed=42,
        )


def test_noise_profile_validates_probabilities() -> None:
    with pytest.raises(ValueError, match="probabilities"):
        NoiseProfile(report_probability=1.5)
    with pytest.raises(ValueError, match="reporting lag"):
        NoiseProfile(min_reporting_lag_minutes=300, max_reporting_lag_minutes=20)

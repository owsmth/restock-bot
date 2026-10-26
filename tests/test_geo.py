import pytest

from restock.geo import haversine_km


def test_haversine_zero_distance() -> None:
    assert haversine_km(26.5629, -81.9495, 26.5629, -81.9495) == 0


def test_haversine_known_city_distance() -> None:
    # Cape Coral to Naples is roughly 49 km straight-line.
    distance = haversine_km(26.5629, -81.9495, 26.1423, -81.7948)
    assert distance == pytest.approx(49.2, abs=0.5)


def test_haversine_is_symmetric() -> None:
    first = haversine_km(26.6406, -81.8723, 26.1423, -81.7948)
    second = haversine_km(26.1423, -81.7948, 26.6406, -81.8723)
    assert first == pytest.approx(second)


def test_haversine_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValueError, match="latitude"):
        haversine_km(91, 0, 0, 0)
    with pytest.raises(ValueError, match="longitude"):
        haversine_km(0, 181, 0, 0)

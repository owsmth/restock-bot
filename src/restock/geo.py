from __future__ import annotations

import math

_EARTH_RADIUS_KM = 6_371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in kilometres between two coordinates."""
    for latitude in (lat1, lat2):
        if not -90.0 <= latitude <= 90.0:
            raise ValueError("latitude must be between -90 and 90")
    for longitude in (lng1, lng2):
        if not -180.0 <= longitude <= 180.0:
            raise ValueError("longitude must be between -180 and 180")

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))

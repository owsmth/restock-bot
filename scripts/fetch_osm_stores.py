from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from restock.db.models import Retailer
from restock.geo import haversine_km

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OVERPASS_TIMEOUT_SECONDS = 90
HTTP_TIMEOUT_SECONDS = 120
USER_AGENT = (
    "restock-agent-osm-review/0.1 "
    "(one-time SouthWest Florida Pokemon restock store candidate export)"
)

# South, west, north, east. Covers Cape Coral, Fort Myers, Bonita Springs, and Naples.
BBOX = (26.04, -82.10, 26.78, -81.62)
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "stores_osm_candidates.csv"
CSV_FIELDS = (
    "retailer",
    "name",
    "address",
    "city",
    "lat",
    "lng",
    "timezone",
    "restock_regime",
    "active",
)

BRAND_LABELS: dict[Retailer, str] = {
    Retailer.DOLLAR_GENERAL: "Dollar General",
    Retailer.FAMILY_DOLLAR: "Family Dollar",
    Retailer.COSTCO: "Costco",
    Retailer.SAMS_CLUB: "Sam's Club",
    Retailer.TARGET: "Target",
    Retailer.WALMART: "Walmart",
    Retailer.BEST_BUY: "Best Buy",
    Retailer.BARNES_NOBLE: "Barnes & Noble",
    Retailer.WALGREENS: "Walgreens",
    Retailer.CVS: "CVS",
}


def _normalize(value: str) -> str:
    without_apostrophes = value.replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", " ", without_apostrophes.casefold()).strip()


# Normalized brand/name prefixes. Order matters where one brand contains another.
BRAND_PATTERNS: tuple[tuple[str, Retailer], ...] = tuple(
    (_normalize(label), retailer) for retailer, label in BRAND_LABELS.items()
)


class OSMQueryError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StoreCandidate:
    retailer: Retailer
    name: str
    address: str
    city: str
    lat: float
    lng: float
    osm_type: str
    osm_id: int

    @property
    def incomplete(self) -> bool:
        return not self.address or not self.city


@dataclass(frozen=True, slots=True)
class ParseSummary:
    elements_seen: int
    matched_elements: int
    unique_candidates: int
    duplicates_removed: int
    incomplete_candidates: int
    skipped_without_coordinates: int
    skipped_unknown_brand: int


def retailer_for_tags(tags: Mapping[str, str]) -> Retailer | None:
    for tag_name in ("brand", "operator", "name"):
        value = _normalize(tags.get(tag_name, ""))
        if not value:
            continue
        for prefix, retailer in BRAND_PATTERNS:
            if value == prefix or value.startswith(prefix + " "):
                return retailer
    return None


def build_overpass_query() -> str:
    brand_pattern = "|".join(BRAND_LABELS.values())
    south, west, north, east = BBOX
    bbox = f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"
    return (
        f"[out:json][timeout:{OVERPASS_TIMEOUT_SECONDS}];\n"
        "(\n"
        f'  nwr["brand"~"{brand_pattern}",i]({bbox});\n'
        f'  nwr["name"~"{brand_pattern}",i]({bbox});\n'
        ");\n"
        "out center tags;"
    )


def fetch_overpass(query: str) -> dict[str, object]:
    request = Request(
        OVERPASS_URL,
        data=urlencode({"data": query}).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            payload = json.load(response)
    except HTTPError as exc:
        raise OSMQueryError(
            f"Overpass returned HTTP {exc.code}. Wait a few minutes and try again."
        ) from exc
    except (TimeoutError, URLError) as exc:
        raise OSMQueryError(f"Could not reach Overpass: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OSMQueryError("Overpass returned invalid JSON.") from exc

    if not isinstance(payload, dict):
        raise OSMQueryError("Overpass returned an unexpected response.")
    payload = cast(dict[str, object], payload)
    if "remark" in payload:
        raise OSMQueryError(f"Overpass reported an error: {payload['remark']}")
    if not isinstance(payload.get("elements"), list):
        raise OSMQueryError("Overpass response did not contain an elements list.")
    return payload


def _tags(raw: Mapping[str, object]) -> dict[str, str]:
    raw_tags = raw.get("tags")
    if not isinstance(raw_tags, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in raw_tags.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _coordinates(raw: Mapping[str, object]) -> tuple[float, float] | None:
    lat = _number(raw.get("lat"))
    lng = _number(raw.get("lon"))
    if lat is not None and lng is not None:
        return lat, lng
    center = raw.get("center")
    if isinstance(center, dict):
        center_lat = _number(center.get("lat"))
        center_lng = _number(center.get("lon"))
        if center_lat is not None and center_lng is not None:
            return center_lat, center_lng
    return None


def _city(tags: Mapping[str, str]) -> str:
    for key in ("addr:city", "addr:town", "addr:village"):
        value = tags.get(key, "").strip()
        if value:
            return value
    return ""


def _street(tags: Mapping[str, str]) -> str:
    street = tags.get("addr:street", "").strip()
    if street:
        return street
    return ""


def _address(tags: Mapping[str, str]) -> str:
    house_number = tags.get("addr:housenumber", "").strip()
    street = _street(tags)
    if house_number and street:
        return f"{house_number} {street}"
    return street


def _candidate_name(
    *,
    retailer: Retailer,
    street: str,
    city: str,
    osm_type: str,
    osm_id: int,
) -> str:
    label = BRAND_LABELS[retailer]
    if street and city:
        return f"{label} - {street}, {city}"
    if street:
        return f"{label} - {street}"
    if city:
        return f"{label} - {city}"
    return f"{label} - OSM {osm_type}/{osm_id}"


def _completeness(candidate: StoreCandidate) -> int:
    return sum(
        (
            bool(candidate.address),
            bool(candidate.city),
            " " in candidate.address,
        )
    )


def _same_store(left: StoreCandidate, right: StoreCandidate) -> bool:
    if left.retailer is not right.retailer:
        return False
    same_address = (
        left.address
        and right.address
        and left.city
        and right.city
        and _normalize(left.address) == _normalize(right.address)
        and _normalize(left.city) == _normalize(right.city)
    )
    if same_address:
        return True
    return haversine_km(left.lat, left.lng, right.lat, right.lng) < 0.05


def parse_overpass(payload: Mapping[str, object]) -> tuple[list[StoreCandidate], ParseSummary]:
    raw_elements = payload.get("elements")
    if not isinstance(raw_elements, list):
        raise OSMQueryError("Overpass response did not contain an elements list.")

    candidates: list[StoreCandidate] = []
    skipped_without_coordinates = 0
    skipped_unknown_brand = 0

    for raw_element in raw_elements:
        if not isinstance(raw_element, dict):
            continue
        tags = _tags(raw_element)
        retailer = retailer_for_tags(tags)
        if retailer is None:
            skipped_unknown_brand += 1
            continue
        coordinates = _coordinates(raw_element)
        if coordinates is None:
            skipped_without_coordinates += 1
            continue
        raw_type = raw_element.get("type")
        raw_id = raw_element.get("id")
        if not isinstance(raw_type, str) or not isinstance(raw_id, int):
            continue
        lat, lng = coordinates
        street = _street(tags)
        city = _city(tags)
        candidates.append(
            StoreCandidate(
                retailer=retailer,
                name=_candidate_name(
                    retailer=retailer,
                    street=street,
                    city=city,
                    osm_type=raw_type,
                    osm_id=raw_id,
                ),
                address=_address(tags),
                city=city,
                lat=lat,
                lng=lng,
                osm_type=raw_type,
                osm_id=raw_id,
            )
        )

    unique: list[StoreCandidate] = []
    for candidate in sorted(candidates, key=_completeness, reverse=True):
        if any(_same_store(candidate, existing) for existing in unique):
            continue
        unique.append(candidate)

    unique.sort(
        key=lambda candidate: (
            candidate.retailer.value,
            candidate.city.casefold(),
            candidate.name.casefold(),
        )
    )
    summary = ParseSummary(
        elements_seen=len(raw_elements),
        matched_elements=len(candidates),
        unique_candidates=len(unique),
        duplicates_removed=len(candidates) - len(unique),
        incomplete_candidates=sum(candidate.incomplete for candidate in unique),
        skipped_without_coordinates=skipped_without_coordinates,
        skipped_unknown_brand=skipped_unknown_brand,
    )
    return unique, summary


def _row(candidate: StoreCandidate) -> dict[str, str]:
    return {
        "retailer": candidate.retailer.value,
        "name": candidate.name,
        "address": candidate.address,
        "city": candidate.city,
        "lat": f"{candidate.lat:.6f}",
        "lng": f"{candidate.lng:.6f}",
        "timezone": "America/New_York",
        "restock_regime": "unknown",
        "active": "true",
    }


def write_candidates(path: Path, candidates: Sequence[StoreCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(_row(candidate) for candidate in candidates)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Export one-time OSM store candidates for manual review. Never writes to the DB."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite the output file if it already exists",
    )
    arguments = parser.parse_args(argv)

    if arguments.output.exists() and not arguments.force:
        print(
            f"Refusing to overwrite {arguments.output}. Review the existing CSV or pass --force.",
            file=sys.stderr,
        )
        return 1

    try:
        payload = fetch_overpass(build_overpass_query())
        candidates, summary = parse_overpass(payload)
    except OSMQueryError as exc:
        print(f"OSM export failed: {exc}", file=sys.stderr)
        return 1

    if not candidates:
        print("OSM export returned no matching store candidates.", file=sys.stderr)
        return 1

    write_candidates(arguments.output, candidates)
    print(
        f"Wrote {len(candidates)} candidates to {arguments.output}. "
        f"OSM elements={summary.elements_seen}, matched={summary.matched_elements}, "
        f"duplicates removed={summary.duplicates_removed}, "
        f"incomplete rows needing hand edits={summary.incomplete_candidates}, "
        f"without coordinates={summary.skipped_without_coordinates}, "
        f"unknown brands={summary.skipped_unknown_brand}. "
        "Review every row before running scripts/seed_stores.py."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

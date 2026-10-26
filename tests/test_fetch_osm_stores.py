from __future__ import annotations

import csv
from pathlib import Path

from scripts.fetch_osm_stores import (
    BBOX,
    USER_AGENT,
    StoreCandidate,
    build_overpass_query,
    main,
    parse_overpass,
    retailer_for_tags,
    write_candidates,
)

from restock.db.models import Retailer

OVERPASS_PAYLOAD: dict[str, object] = {
    "elements": [
        {
            "type": "node",
            "id": 1,
            "lat": 26.6406,
            "lon": -81.8723,
            "tags": {
                "brand": "Target",
                "name": "Target",
                "addr:housenumber": "123",
                "addr:street": "Colonial Blvd",
                "addr:city": "Fort Myers",
            },
        },
        {
            "type": "way",
            "id": 2,
            "center": {"lat": 26.6406, "lon": -81.8723},
            "tags": {
                "brand": "Target",
                "name": "Target",
                "addr:housenumber": "123",
                "addr:street": "Colonial Blvd",
                "addr:city": "Fort Myers",
            },
        },
        {
            "type": "node",
            "id": 3,
            "lat": 26.5629,
            "lon": -81.9495,
            "tags": {
                "name": "CVS Pharmacy",
                "addr:housenumber": "5",
                "addr:street": "Main St",
                "addr:city": "Cape Coral",
            },
        },
        {
            "type": "node",
            "id": 4,
            "lat": 26.1423,
            "lon": -81.7948,
            "tags": {"name": "Family Dollar", "addr:city": "Naples"},
        },
        {
            "type": "node",
            "id": 5,
            "lat": 26.3398,
            "lon": -81.7787,
            "tags": {"name": "Some Unrelated Store"},
        },
        {"type": "node", "id": 6, "tags": {"name": "Walgreens"}},
    ]
}


def test_retailer_mapping_handles_brand_and_name_variants() -> None:
    assert retailer_for_tags({"brand": "Sam's Club"}) is Retailer.SAMS_CLUB
    assert retailer_for_tags({"brand": "Costco Wholesale"}) is Retailer.COSTCO
    assert retailer_for_tags({"name": "Barnes & Noble Booksellers"}) is Retailer.BARNES_NOBLE
    assert retailer_for_tags({"name": "Family Dollar"}) is Retailer.FAMILY_DOLLAR
    assert retailer_for_tags({"name": "Unrelated"}) is None


def test_overpass_query_is_one_query_for_the_target_bbox() -> None:
    query = build_overpass_query()

    south, west, north, east = BBOX
    assert f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}" in query
    assert query.count("nwr[") == 2
    assert "Barnes & Noble" in query
    assert "Family Dollar" in query
    assert "restock-agent-osm-review" in USER_AGENT


def test_parse_overpass_deduplicates_and_keeps_incomplete_rows_for_review() -> None:
    candidates, summary = parse_overpass(OVERPASS_PAYLOAD)

    assert summary.elements_seen == 6
    assert summary.matched_elements == 4
    assert summary.unique_candidates == 3
    assert summary.duplicates_removed == 1
    assert summary.incomplete_candidates == 1
    assert summary.skipped_unknown_brand == 1
    assert summary.skipped_without_coordinates == 1

    by_retailer = {candidate.retailer: candidate for candidate in candidates}
    target = by_retailer[Retailer.TARGET]
    assert target.name == "Target - Colonial Blvd, Fort Myers"
    assert target.address == "123 Colonial Blvd"
    assert target.city == "Fort Myers"
    assert (target.lat, target.lng) == (26.6406, -81.8723)

    cvs = by_retailer[Retailer.CVS]
    assert cvs.name == "CVS - Main St, Cape Coral"
    assert cvs.address == "5 Main St"

    family_dollar = by_retailer[Retailer.FAMILY_DOLLAR]
    assert family_dollar.name == "Family Dollar - Naples"
    assert family_dollar.address == ""
    assert family_dollar.incomplete is True


def test_write_candidates_uses_seed_columns(tmp_path: Path) -> None:
    candidate = StoreCandidate(
        retailer=Retailer.WALGREENS,
        name="Walgreens - Main St, Naples",
        address="10 Main St",
        city="Naples",
        lat=26.1423,
        lng=-81.7948,
        osm_type="node",
        osm_id=99,
    )
    output = tmp_path / "candidates.csv"

    write_candidates(output, [candidate])

    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == [
        "retailer",
        "name",
        "address",
        "city",
        "lat",
        "lng",
        "timezone",
        "restock_regime",
        "active",
    ]
    assert rows[0]["retailer"] == "walgreens"
    assert rows[0]["name"] == "Walgreens - Main St, Naples"
    assert rows[0]["active"] == "true"
    assert rows[0]["restock_regime"] == "unknown"


def test_main_refuses_to_overwrite_an_existing_file(tmp_path: Path) -> None:
    output = tmp_path / "existing.csv"
    output.write_text("do not replace", encoding="utf-8")

    assert main(["--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "do not replace"

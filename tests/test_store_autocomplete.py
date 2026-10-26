from __future__ import annotations

from restock.bot.formatting import format_store_autocomplete
from restock.db.models import RestockRegime, Retailer
from restock.services.stores import AUTOCOMPLETE_LIMIT, StoreSummary, rank_store_matches


def _store(
    store_id: int,
    *,
    retailer: Retailer,
    name: str,
    address: str,
    city: str,
) -> StoreSummary:
    return StoreSummary(
        id=store_id,
        retailer=retailer,
        name=name,
        address=address,
        city=city,
        timezone="America/New_York",
        restock_regime=RestockRegime.UNKNOWN,
    )


def _hundred_stores() -> list[StoreSummary]:
    stores = [
        _store(
            1,
            retailer=Retailer.TARGET,
            name="Target - Colonial Blvd, Fort Myers",
            address="Colonial Blvd",
            city="Fort Myers",
        ),
        _store(
            2,
            retailer=Retailer.TARGET,
            name="Target - Colonial Blvd, Fort Myers",
            address="123 Colonial Blvd",
            city="Fort Myers",
        ),
        _store(
            3,
            retailer=Retailer.WALMART,
            name="Walmart - Colonial Blvd, Fort Myers",
            address="500 Colonial Blvd",
            city="Fort Myers",
        ),
    ]
    retailers = (
        Retailer.TARGET,
        Retailer.WALMART,
        Retailer.SAMS_CLUB,
        Retailer.COSTCO,
        Retailer.BEST_BUY,
        Retailer.DOLLAR_GENERAL,
        Retailer.FAMILY_DOLLAR,
        Retailer.BARNES_NOBLE,
        Retailer.WALGREENS,
        Retailer.CVS,
    )
    for index in range(4, 101):
        retailer = retailers[index % len(retailers)]
        city = "Cape Coral" if index % 3 else "Naples"
        street = f"{100 + index} Example Blvd"
        stores.append(
            _store(
                index,
                retailer=retailer,
                name=f"{retailer.value.replace('_', ' ').title()} - {street}, {city}",
                address=street,
                city=city,
            )
        )
    return stores


def test_autocomplete_matches_tokens_across_fields_case_insensitively() -> None:
    stores = _hundred_stores()

    target_cape = rank_store_matches(stores, "TARGET cape")
    assert target_cape
    assert all(store.retailer is Retailer.TARGET for store in target_cape)
    assert all(store.city == "Cape Coral" for store in target_cape)

    address_match = rank_store_matches(stores, "colonial fort")
    assert {store.id for store in address_match} == {1, 2, 3}

    retailer_only = _store(
        101,
        retailer=Retailer.BEST_BUY,
        name="Electronics Store",
        address="900 Example Blvd",
        city="Naples",
    )
    assert [store.id for store in rank_store_matches([retailer_only], "best buy")] == [101]
    assert rank_store_matches([retailer_only], "barnes") == []


def test_autocomplete_ranks_field_prefixes_first() -> None:
    stores = _hundred_stores()

    results = rank_store_matches(stores, "colonial")

    assert [store.id for store in results[:3]] == [1, 2, 3]


def test_autocomplete_limits_choices_to_25_and_handles_empty_query() -> None:
    stores = _hundred_stores()

    assert len(rank_store_matches(stores, "example")) == AUTOCOMPLETE_LIMIT
    assert len(rank_store_matches(stores, "example", limit=100)) == AUTOCOMPLETE_LIMIT
    assert len(rank_store_matches(stores, "")) == AUTOCOMPLETE_LIMIT
    assert rank_store_matches(stores, "no such store") == []


def test_autocomplete_labels_match_requested_shape_and_are_truncated() -> None:
    store = _store(
        7,
        retailer=Retailer.TARGET,
        name="Target - 123 Colonial Blvd, Fort Myers",
        address="123 Colonial Blvd",
        city="Fort Myers",
    )

    assert format_store_autocomplete(store) == "Target - 123 Colonial Blvd, Fort Myers"

    long_store = _store(
        8,
        retailer=Retailer.BARNES_NOBLE,
        name="Barnes & Noble - Long Address",
        address="9 " + "Very Long Street " * 10,
        city="Naples",
    )
    assert len(format_store_autocomplete(long_store)) == 100

    no_address = _store(
        9,
        retailer=Retailer.WALGREENS,
        name="Walgreens - Main St",
        address="",
        city="Bonita Springs",
    )
    assert format_store_autocomplete(no_address) == "Walgreens - Main St, Bonita Springs"

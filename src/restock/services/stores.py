from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from restock.db.models import RestockRegime, Retailer, Store
from restock.db.session import SessionFactory, session_scope
from restock.repositories.stores import StoreRepository
from restock.services.errors import StoreInactiveError, StoreNotFoundError

AUTOCOMPLETE_LIMIT = 25


def _normalize_search_text(value: str) -> str:
    without_apostrophes = value.replace("'", "").replace("\u2019", "")
    return re.sub(r"[^a-z0-9]+", " ", without_apostrophes.casefold()).strip()


def _search_fields(store: StoreSummary) -> tuple[str, ...]:
    return (
        _normalize_search_text(store.retailer.value),
        _normalize_search_text(store.name),
        _normalize_search_text(store.city),
        _normalize_search_text(store.address),
    )


def rank_store_matches(
    stores: Sequence[StoreSummary],
    query: str,
    *,
    limit: int = AUTOCOMPLETE_LIMIT,
) -> list[StoreSummary]:
    effective_limit = max(0, min(limit, AUTOCOMPLETE_LIMIT))
    normalized_query = _normalize_search_text(query)
    if not query.strip():
        ordered = sorted(stores, key=lambda store: (store.name.casefold(), store.id))
        return ordered[:effective_limit]
    if not normalized_query:
        return []

    tokens = normalized_query.split()
    ranked: list[tuple[tuple[bool, int, str, int], StoreSummary]] = []
    for store in stores:
        fields = _search_fields(store)
        search_text = " ".join(fields)
        if not all(token in search_text for token in tokens):
            continue
        words = search_text.split()
        prefix_count = sum(1 for token in tokens if any(word.startswith(token) for word in words))
        field_prefix = any(field.startswith(normalized_query) for field in fields if field)
        ranked.append(
            (
                (not field_prefix, -prefix_count, store.name.casefold(), store.id),
                store,
            )
        )

    ranked.sort(key=lambda item: item[0])
    return [store for _, store in ranked[:effective_limit]]


@dataclass(frozen=True, slots=True)
class StoreSummary:
    id: int
    retailer: Retailer
    name: str
    address: str
    city: str
    timezone: str
    restock_regime: RestockRegime
    active: bool = True

    @classmethod
    def from_model(cls, store: Store) -> StoreSummary:
        return cls(
            id=store.id,
            retailer=store.retailer,
            name=store.name,
            address=store.address,
            city=store.city,
            timezone=store.timezone,
            restock_regime=store.restock_regime,
            active=store.active,
        )


class StoreService:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def list_active(self, retailer: Retailer | None = None) -> list[StoreSummary]:
        with session_scope(self._session_factory) as session:
            stores = StoreRepository(session).list_active(retailer)
            return [StoreSummary.from_model(store) for store in stores]

    def search_active(self, query: str, *, limit: int = AUTOCOMPLETE_LIMIT) -> list[StoreSummary]:
        with session_scope(self._session_factory) as session:
            stores = StoreRepository(session).list_active()
            summaries = [StoreSummary.from_model(store) for store in stores]
        return rank_store_matches(summaries, query, limit=limit)

    def search_all(self, query: str, *, limit: int = AUTOCOMPLETE_LIMIT) -> list[StoreSummary]:
        with session_scope(self._session_factory) as session:
            stores = StoreRepository(session).list_all()
            summaries = [StoreSummary.from_model(store) for store in stores]
        return rank_store_matches(summaries, query, limit=limit)

    def set_active(self, store_id: int, active: bool) -> StoreSummary:
        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).set_active(store_id, active)
            if store is None:
                raise StoreNotFoundError(store_id)
            return StoreSummary.from_model(store)

    def get_active(self, store_id: int) -> StoreSummary:
        with session_scope(self._session_factory) as session:
            store = StoreRepository(session).get(store_id)
            if store is None:
                raise StoreNotFoundError(store_id)
            if not store.active:
                raise StoreInactiveError(store.name)
            return StoreSummary.from_model(store)

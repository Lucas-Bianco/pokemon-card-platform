from datetime import datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from cardplatform.db.models import Card, CardSet, CollectionItem, PriceSnapshot


def test_can_persist_a_set(db):
    s = CardSet(
        id="base1",
        name="Base",
        series="Base",
        printed_total=102,
        total=102,
        ptcgo_code="BS",
        release_date="1999/01/09",
        image_symbol="https://images.pokemontcg.io/base1/symbol.png",
        image_logo="https://images.pokemontcg.io/base1/logo.png",
    )
    db.add(s)
    db.commit()

    got = db.get(CardSet, "base1")
    assert got.name == "Base"
    assert got.printed_total == 102


def test_can_persist_a_card_linked_to_set(db):
    db.add(CardSet(id="base1", name="Base", series="Base", printed_total=102, total=102))
    db.add(
        Card(
            id="base1-4",
            set_id="base1",
            name="Charizard",
            number="4",
            rarity="Rare Holo",
            supertype="Pokémon",
            subtypes=["Stage 2"],
            artist="Mitsuhiro Arita",
            image_small="https://images.pokemontcg.io/base1/4.png",
            image_large="https://images.pokemontcg.io/base1/4_hires.png",
        )
    )
    db.commit()

    card = db.get(Card, "base1-4")
    assert card.name == "Charizard"
    assert card.card_set.name == "Base"
    assert card.subtypes == ["Stage 2"]


def test_accented_names_survive_roundtrip(db):
    """Guards the cp1252 mojibake bug: 'Pokémon' must not become 'PokÃ©mon'."""
    db.add(CardSet(id="base1", name="Base", series="Base", printed_total=102, total=102))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4", supertype="Pokémon"))
    db.commit()
    db.expunge_all()

    card = db.get(Card, "base1-4")
    assert card.supertype == "Pokémon"
    assert "Ã" not in card.supertype


def _seed_card(db) -> None:
    db.add(CardSet(id="base1", name="Base", series="Base", printed_total=102, total=102))
    db.add(Card(id="base1-4", set_id="base1", name="Charizard", number="4"))
    db.commit()


def test_duplicate_snapshot_is_rejected_by_unique_constraint(db):
    _seed_card(db)
    db.add(
        PriceSnapshot(
            card_id="base1-4", source="tcgplayer", variant="holofoil", source_updated_at="2024/01/01"
        )
    )
    db.commit()

    db.add(
        PriceSnapshot(
            card_id="base1-4", source="tcgplayer", variant="holofoil", source_updated_at="2024/01/01"
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_snapshots_missing_source_updated_at_also_dedupe(db):
    """Regression guard for Fix 1: the '' sentinel must collide, unlike NULL."""
    _seed_card(db)
    db.add(PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil"))
    db.commit()

    db.add(PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil"))
    with pytest.raises(IntegrityError):
        db.commit()


def test_snapshot_with_differing_timestamp_inserts_new_row(db):
    _seed_card(db)
    db.add(
        PriceSnapshot(
            card_id="base1-4", source="tcgplayer", variant="holofoil", source_updated_at="2024/01/01"
        )
    )
    db.add(
        PriceSnapshot(
            card_id="base1-4", source="tcgplayer", variant="holofoil", source_updated_at="2024/01/02"
        )
    )
    db.commit()

    count = db.query(PriceSnapshot).filter_by(card_id="base1-4").count()
    assert count == 2


def test_snapshot_fetched_at_autopopulates_as_tzaware_utc(db):
    """Regression guard for Fix 2: must round-trip tz-aware, not naive."""
    _seed_card(db)
    snap = PriceSnapshot(card_id="base1-4", source="tcgplayer", variant="holofoil")
    db.add(snap)
    db.commit()
    db.expunge_all()

    got = db.query(PriceSnapshot).filter_by(card_id="base1-4").one()
    assert got.fetched_at.tzinfo is not None
    # Must not raise TypeError comparing aware to aware.
    assert got.fetched_at <= datetime.now(timezone.utc)


def test_collection_item_defaults(db):
    _seed_card(db)
    item = CollectionItem(card_id="base1-4")
    db.add(item)
    db.commit()
    db.expunge_all()

    got = db.query(CollectionItem).filter_by(card_id="base1-4").one()
    assert got.variant == "normal"
    assert got.quantity == 1


def test_card_with_nonexistent_set_id_violates_foreign_key(db):
    """Regression guard for Fix 3: FKs must be enforced in tests, same as production."""
    db.add(Card(id="orphan-1", set_id="does-not-exist", name="Orphan", number="1"))
    with pytest.raises(IntegrityError):
        db.commit()

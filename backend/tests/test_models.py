from cardplatform.db.models import Card, CardSet


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

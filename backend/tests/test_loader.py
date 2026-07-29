from cardplatform.catalog.loader import CatalogLoader
from cardplatform.db.models import Card, CardSet

SET_PAYLOAD = [
    {
        "id": "base1",
        "name": "Base",
        "series": "Base",
        "printedTotal": 102,
        "total": 102,
        "ptcgoCode": "BS",
        "releaseDate": "1999/01/09",
        "images": {
            "symbol": "https://images.pokemontcg.io/base1/symbol.png",
            "logo": "https://images.pokemontcg.io/base1/logo.png",
        },
    }
]

CARD_PAYLOAD = [
    {
        "id": "base1-4",
        "name": "Charizard",
        "number": "4",
        "rarity": "Rare Holo",
        "supertype": "Pokémon",
        "subtypes": ["Stage 2"],
        "artist": "Mitsuhiro Arita",
        "nationalPokedexNumbers": [6],
        "images": {
            "small": "https://images.pokemontcg.io/base1/4.png",
            "large": "https://images.pokemontcg.io/base1/4_hires.png",
        },
    }
]


class FakeDump:
    def __init__(self, sets, cards_by_set):
        self._sets = sets
        self._cards = cards_by_set

    def fetch_sets(self):
        return self._sets

    def fetch_cards(self, set_id):
        return self._cards.get(set_id, [])


def test_loads_sets_and_cards(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))

    result = loader.load_all()

    assert result.sets_seen == 1
    assert result.cards_seen == 1
    assert result.cards_inserted == 1
    assert result.cards_updated == 0
    card = db.get(Card, "base1-4")
    assert card.name == "Charizard"
    assert card.supertype == "Pokémon"
    assert card.image_small.endswith("/base1/4.png")
    assert card.national_pokedex_numbers == [6]
    assert db.get(CardSet, "base1").ptcgo_code == "BS"


def test_load_is_idempotent(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))

    loader.load_all()
    second = loader.load_all()

    assert second.cards_seen == 1
    assert second.cards_inserted == 0
    assert second.cards_updated == 1
    assert db.query(Card).count() == 1
    assert db.query(CardSet).count() == 1


def test_reload_updates_changed_fields(db):
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": CARD_PAYLOAD}))
    loader.load_all()

    updated = [dict(CARD_PAYLOAD[0], rarity="Rare Holo VMAX")]
    CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": updated})).load_all()

    assert db.get(Card, "base1-4").rarity == "Rare Holo VMAX"


def test_missing_optional_fields_are_tolerated(db):
    sparse = [{"id": "base1-5", "name": "Clefairy", "number": "5"}]
    loader = CatalogLoader(db, FakeDump(SET_PAYLOAD, {"base1": sparse}))

    loader.load_all()

    card = db.get(Card, "base1-5")
    assert card.rarity is None
    assert card.image_small is None

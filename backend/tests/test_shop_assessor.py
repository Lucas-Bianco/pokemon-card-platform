"""Phase E: ShopAssessor — match an eBay listing to a sealed product or card,
compute a deal edge, and (for cards) surface the authenticity guide.

In-process SQLite via the shared `db` fixture (create_all, tmp dir). No network:
a stub provider returns canned SealedListing / SealedSoldComp instances. Sacred
invariants asserted: market None (never 0), empty states honest, authenticity is
a guide (never a fake/real verdict).
"""
from __future__ import annotations

import pytest

from cardplatform.config import Settings
from cardplatform.db.models import Card, CardSet, PriceSnapshot
from cardplatform.sealed.catalog_service import SealedCatalogService
from cardplatform.sealed.provider import SealedListing, SealedSoldComp
from cardplatform.sealed.seed_data import SEALED_PRODUCTS
from cardplatform.shop.api_models import ShopAssessmentOut
from cardplatform.shop.assess import ShopAssessor


EBAY_URL = "https://www.ebay.com/itm/123456789"
EBAY_ITEM_ID = "123456789"


class StubProvider:
    """Stand-in for EbayListingsProvider — returns canned data, no network."""

    def __init__(self, listing=None, comps=None):
        self.listing = listing
        self.comps = comps or []

    def fetch_listing_by_id(self, item_id):
        return self.listing

    def fetch_sold_listings_by_query(self, query, limit):
        return self.comps


def _listing(title, price=15.0):
    return SealedListing(
        query="", listing_id=EBAY_ITEM_ID, source="ebay",
        title=title, price=price, currency="USD",
        listing_type="fixed_price", auction_end_at=None,
        url=EBAY_URL, condition="New", source_updated_at=None,
        seller="seller1", image_url="https://img/x",
    )


def _comp(price):
    return SealedSoldComp(
        query="", listing_id="c" + str(price), price=price,
        title="sold", currency="USD", url="https://ebay/s",
        condition="Used", sold_at=None, source="ebay",
    )


@pytest.fixture
def seeded(db):
    """Seed the sealed catalog + a couple of cards + a price snapshot."""
    SealedCatalogService(db).ensure_seed(SEALED_PRODUCTS)
    db.add(CardSet(id="base1", name="Base", series="Base", release_date="1999/01/09"))
    db.add(CardSet(id="swsh1", name="Sword & Shield", series="Sword & Shield"))
    # Charizard: number 12 (so "12/102" in a title matches), Holo Rare (holo gate).
    db.add(Card(
        id="base1-2", set_id="base1", name="Charizard", number="12",
        rarity="Holo Rare", image_small="s", image_large="l",
    ))
    db.add(Card(
        id="base1-1", set_id="base1", name="Bulbasaur", number="1",
        rarity="Common", image_small="s", image_large="l",
    ))
    db.commit()
    return db


def _snap(db, card_id, market, source="tcgplayer", variant="normal", stamp="2026/08/01"):
    db.add(PriceSnapshot(
        card_id=card_id, source=source, variant=variant, market=market,
        source_updated_at=stamp,
    ))
    db.commit()


def _assessor(db, *, key=None, listing=None, comps=None):
    # The assessor only reads listings_api_key + the flip/rip thresholds from
    # settings. Pin data_dir to a tmp path so we never touch the real repo data.
    import tempfile
    settings = Settings(data_dir=tempfile.gettempdir(), listings_api_key=key)
    return ShopAssessor(db, settings, StubProvider(listing=listing, comps=comps)), settings


# ---- 1. sealed match + deal ----

def test_sealed_match_with_comps_is_deal(seeded):
    listing = _listing("Scarlet & Violet Elite Trainer Box", price=15.0)
    comps = [_comp(38.0), _comp(40.0), _comp(42.0)]
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=comps)

    a = assessor.assess(EBAY_URL)

    assert a.item_id == EBAY_ITEM_ID
    assert a.listing_unavailable is False
    assert a.listing is not None
    assert a.match.kind == "sealed"
    assert a.match.confidence == "high"
    assert a.match.sealed_slug == "scarlet-violet-elite-trainer-box"
    assert a.match.sealed_name == "Scarlet & Violet Elite Trainer Box"
    assert a.deal is not None
    assert a.deal.market == 40.0  # median of [38,40,42]
    assert a.deal.market_source == "ebay"
    assert a.deal.sold_comps_count == 3
    assert a.deal.edge == 25.0  # 40 - 15
    assert a.deal.is_deal is True  # 25 >= 20 (min_abs) and 25 >= 0.05*40 (min_pct)
    assert a.deal.market_unavailable is False
    assert a.deal.market_empty is False
    assert a.authenticity is None  # sealed -> no authenticity


# ---- 2. sealed no key -> unavailable ----

def test_sealed_no_key_listing_unavailable(seeded):
    listing = _listing("Scarlet & Violet Elite Trainer Box", price=15.0)
    comps = [_comp(40.0)]
    assessor, settings = _assessor(seeded, key=None, listing=listing, comps=comps)

    a = assessor.assess(EBAY_URL)

    assert a.listing_unavailable is True
    assert a.listing is None
    # No raw -> match is none -> deal None.
    assert a.match.kind == "none"
    assert a.deal is None
    assert a.authenticity is None
    assert a.listing_not_found is False  # not found is only when key set + raw None


# ---- 3. sealed market_empty ----

def test_sealed_market_empty_when_no_comps(seeded):
    listing = _listing("Scarlet & Violet Elite Trainer Box", price=15.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.match.kind == "sealed"
    assert a.deal is not None
    assert a.deal.market is None  # never 0
    assert a.deal.edge is None
    assert a.deal.is_deal is False
    assert a.deal.market_empty is True
    assert a.deal.market_unavailable is False
    assert a.deal.sold_comps_count == 0


# ---- 4. card match + deal ----

def test_card_match_with_snapshot_is_deal(seeded):
    _snap(seeded, "base1-2", market=100.0, source="tcgplayer", stamp="2026/08/01")
    listing = _listing("Charizard 12/102", price=80.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.match.kind == "card"
    assert a.match.confidence == "low"
    assert a.match.card_id == "base1-2"
    assert a.match.card_name == "Charizard"
    assert a.match.card_number == "12"
    assert a.match.card_rarity == "Holo Rare"
    assert a.match.set_name == "Base"
    assert a.deal is not None
    assert a.deal.market == 100.0
    assert a.deal.market_source == "tcgplayer"
    assert a.deal.market_source_updated_at == "2026/08/01"
    assert a.deal.sold_comps_count == 0
    assert a.deal.edge == 20.0  # 100 - 80
    assert a.deal.is_deal is True  # 20 >= 2 and 20 >= 0.10*100
    assert a.deal.market_empty is False


# ---- 5. card no snapshot ----

def test_card_no_snapshot_market_none(seeded):
    listing = _listing("Charizard 12/102", price=80.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.match.kind == "card"
    assert a.deal is not None
    assert a.deal.market is None  # never 0
    assert a.deal.market_source is None
    assert a.deal.edge is None
    assert a.deal.is_deal is False
    assert a.deal.market_empty is True


# ---- 6. no match ----

def test_no_match_gibberish_title(seeded):
    listing = _listing("gibberish xyz widget", price=10.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.match.kind == "none"
    assert a.match.confidence == "low"
    assert a.deal is None
    assert a.authenticity is None


# ---- 7. authenticity match ----

def test_authenticity_printed_number_matches(seeded):
    _snap(seeded, "base1-2", market=100.0)
    listing = _listing("Charizard 12/102", price=80.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.authenticity is not None
    assert a.authenticity.consistency.match == "match"
    assert a.authenticity.consistency.printed_number == "12"
    assert a.authenticity.consistency.catalog_number == "12"


# ---- 8. authenticity unread ----

def test_authenticity_no_printed_number_is_unread(seeded):
    _snap(seeded, "base1-2", market=100.0)
    listing = _listing("Charizard promo", price=80.0)  # no NN/NN
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)

    assert a.authenticity is not None
    assert a.authenticity.consistency.match == "unread"
    assert a.authenticity.consistency.printed_number is None


# ---- 9. holo gate ----

def test_checklist_holo_gate(seeded):
    _snap(seeded, "base1-2", market=100.0)
    _snap(seeded, "base1-1", market=5.0)
    assessor, settings = _assessor(
        seeded, key="test-key",
        listing=_listing("Charizard 12/102", price=80.0), comps=[],
    )

    # Holo Rare card -> holo item applies.
    a_holo = assessor.assess(EBAY_URL)
    assert a_holo.match.card_rarity == "Holo Rare"
    holo_items = {i.id: i for i in a_holo.authenticity.checklist}
    assert holo_items["holo_light"].applies is True

    # Common card -> holo item does not apply.
    assessor2, _ = _assessor(
        seeded, key="test-key",
        listing=_listing("Bulbasaur", price=1.0), comps=[],
    )
    a_common = assessor2.assess(EBAY_URL)
    assert a_common.match.card_rarity == "Common"
    common_items = {i.id: i for i in a_common.authenticity.checklist}
    assert common_items["holo_light"].applies is False


# ---- 10. item_id None (defensive) ----

def test_non_ebay_url_does_not_crash(seeded):
    assessor, settings = _assessor(seeded, key="test-key", listing=None, comps=[])

    a = assessor.assess("https://example.com/x")

    assert a.item_id is None
    assert a.listing is None
    assert a.match.kind == "none"
    assert a.deal is None
    assert a.authenticity is None
    assert a.listing_unavailable is False  # key IS set; raw None -> not_found
    assert a.listing_not_found is True


# ---- 11. wire model round-trip ----

def test_assessment_serializes_to_pydantic(seeded):
    listing = _listing("Charizard 12/102", price=80.0)
    _snap(seeded, "base1-2", market=100.0)
    assessor, settings = _assessor(seeded, key="test-key", listing=listing, comps=[])

    a = assessor.assess(EBAY_URL)
    out = ShopAssessmentOut.model_validate(a)

    assert out.url == EBAY_URL
    assert out.match.kind == "card"
    assert out.deal.is_deal is True
    assert out.authenticity is not None
    assert out.authenticity.consistency.match == "match"
    assert out.authenticity.checklist  # non-empty
    assert "not a verdict" in out.caveat.lower()
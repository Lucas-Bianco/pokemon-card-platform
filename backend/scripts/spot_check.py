"""Verifies the loaded catalog, especially that UTF-8 survived the load."""

from cardplatform.db.models import Card
from cardplatform.db.session import Database

with Database().session() as session:
    card = session.get(Card, "base1-4")
    assert card is not None, "base1-4 missing — catalog did not load"
    print("name:      ", repr(card.name))
    print("supertype: ", repr(card.supertype))
    print("set:       ", card.card_set.name)
    print("image:     ", card.image_small)
    assert "Ã" not in (card.supertype or ""), "MOJIBAKE — utf-8 decode regressed in dump.py"
    print("OK")

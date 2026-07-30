"""HTTP read/write layer over the local catalog, prices, and collection."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.collection.store import CollectionStore
from cardplatform.db.models import Card, CollectionItem, PriceSnapshot, ScanLog
from cardplatform.db.session import Database
from cardplatform.prices.service import PriceService
from cardplatform.scans.store import ScanStore

_database: Database | None = None


def _get_database() -> Database:
    """Build the Database on first request, not at import time.

    Constructing it here keeps `import cardplatform.api` side-effect free — the test
    suite overrides get_session and must never create or touch the real data file
    just by importing this module.
    """
    global _database
    if _database is None:
        database = Database()
        database.create_all()
        _database = database
    return _database


def get_session() -> Iterator[Session]:
    with _get_database().session() as session:
        yield session


_recognition_stack: dict | None = None


def get_recognition_stack() -> dict:
    """Load CLIP weights and the FAISS index once per process.

    Building these per request would add seconds to every scan. Imports are local for
    the same reason _get_database is lazy: importing this module must not drag in torch
    or require an index to exist on disk.
    """
    global _recognition_stack
    if _recognition_stack is None:
        from cardplatform.recognition.encoder import CardEncoder
        from cardplatform.recognition.index import CardIndex
        from cardplatform.recognition.ocr import CollectorNumberReader

        _recognition_stack = {
            "encoder": CardEncoder(),
            "index": CardIndex().load(),
            "reader": CollectorNumberReader(),
        }
    return _recognition_stack


def get_price_provider():
    """The live price source. A dependency so tests can stub it out — the real one
    talks to an API measured at roughly a 17% success rate."""
    from cardplatform.prices.pokemontcg import PokemonTcgIoProvider

    return PokemonTcgIoProvider()


def get_scan_store(session: Session = Depends(get_session)) -> ScanStore:
    """Scan storage for this request.

    A dependency so tests can point it at a temp directory — otherwise the module-level
    settings singleton wins and test runs litter the real data directory.
    """
    return ScanStore(session)


def get_recognition_service(session: Session = Depends(get_session)):
    """Per-request recognition service bound to this request's session.

    Declared as a dependency so tests can override it with a stub and never load real
    model weights or require a built index on disk.
    """
    from cardplatform.recognition.service import RecognitionService

    stack = get_recognition_stack()
    return RecognitionService(
        session=session,
        encoder=stack["encoder"],
        index=stack["index"],
        reader=stack["reader"],
    )


class CardOut(BaseModel):
    id: str
    name: str
    number: str
    rarity: str | None
    set_id: str
    set_name: str
    image_small: str | None
    image_large: str | None

    @classmethod
    def from_card(cls, card: Card) -> "CardOut":
        return cls(
            id=card.id,
            name=card.name,
            number=card.number,
            rarity=card.rarity,
            set_id=card.set_id,
            set_name=card.card_set.name,
            image_small=card.image_small,
            image_large=card.image_large,
        )


class PriceOut(BaseModel):
    """A price is never returned bare.

    `source` and `source_updated_at` travel with every figure so the UI can say where
    a number came from and how old it is, instead of implying everything is current —
    tcgplayer refreshes daily, cardmarket has been measured ~4 weeks behind.
    `fetched_at` is when we pulled it, which is a different question from when the
    source last moved it.
    """

    source: str
    variant: str
    low: float | None
    mid: float | None
    high: float | None
    market: float | None
    source_updated_at: str
    fetched_at: datetime


class CandidateOut(BaseModel):
    """A runner-up the user may have to choose between, resolved against the catalog.

    A bare card_id is unusable in a picker, so the name, set, number and thumbnail
    travel with the score.
    """

    card_id: str
    name: str
    set_name: str
    number: str
    image_small: str | None
    visual_score: float


class RecognizeOut(BaseModel):
    """The scan verdict, with the pipeline's reasoning attached.

    `card` and `price` are only populated for a result that actually named a card;
    `collector_number_read` is exposed so the UI can show what OCR saw rather than
    presenting the match as an oracle.
    """

    status: str
    confidence: float
    visual_margin: float
    card: CardOut | None
    price: PriceOut | None
    candidates: list[CandidateOut]
    collector_number_read: str | None


class ScanOut(BaseModel):
    id: int
    status: str
    predicted_card_id: str | None
    corrected_card_id: str | None
    confirmed: bool
    confidence: float | None
    visual_margin: float | None
    collector_number_read: str | None


class ScanAccuracyOut(BaseModel):
    total: int
    answered: int
    predicted: int
    correct: int
    precision: float
    coverage: float
    by_status: dict[str, int]


class CollectionItemIn(BaseModel):
    card_id: str
    variant: str = "normal"
    quantity: int = Field(default=1, ge=1)
    acquired_price: float | None = None
    condition: str | None = None


class CollectionItemOut(BaseModel):
    id: int
    card_id: str
    card_name: str
    variant: str
    quantity: int
    acquired_price: float | None
    condition: str | None


class ValuationOut(BaseModel):
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


def create_app() -> FastAPI:
    app = FastAPI(title="ClaudeKnowledge", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cards", response_model=list[CardOut])
    def search_cards(
        name: str = Query(min_length=1),
        limit: int = Query(default=25, ge=1, le=100),
        session: Session = Depends(get_session),
    ) -> list[CardOut]:
        # lower() rather than ilike(): SQLite's LIKE is only case-insensitive for
        # ASCII, and the catalog carries accented names (e.g. "Flabébé").
        pattern = f"%{name.lower()}%"
        cards = session.scalars(
            select(Card)
            .where(func.lower(Card.name).like(pattern))
            .order_by(Card.name, Card.id)
            .limit(limit)
        ).all()
        return [CardOut.from_card(card) for card in cards]

    @app.get("/cards/{card_id}", response_model=CardOut)
    def get_card(card_id: str, session: Session = Depends(get_session)) -> CardOut:
        return CardOut.from_card(_require_card(session, card_id))

    @app.get("/cards/{card_id}/prices", response_model=list[PriceOut])
    def get_card_prices(card_id: str, session: Session = Depends(get_session)) -> list[PriceOut]:
        _require_card(session, card_id)

        # Snapshots are append-only history, so one card accrues many rows per
        # (source, variant). Walking newest-first and keeping the first row seen for
        # each pair yields the current price from every source we track.
        snapshots = session.scalars(
            select(PriceSnapshot)
            .where(PriceSnapshot.card_id == card_id)
            .order_by(PriceSnapshot.fetched_at.desc(), PriceSnapshot.id.desc())
        ).all()

        latest: dict[tuple[str, str], PriceSnapshot] = {}
        for snapshot in snapshots:
            latest.setdefault((snapshot.source, snapshot.variant), snapshot)
        return [_price_out(s) for s in latest.values()]

    @app.get("/cards/{card_id}/price")
    def resolved_price(
        card_id: str,
        variant: str = Query(default="normal"),
        session: Session = Depends(get_session),
    ) -> Response:
        """The single price to show for this card and variant, or 204 if unpriced.

        `/cards/{id}/prices` returns every source and variant; this applies the
        tcgplayer-then-cardmarket resolution rule so callers do not reimplement it.

        Returns a bare Response rather than declaring a response_model: a 204 must
        carry no body, and returning `None` under a response_model would serialise a
        literal `null`, which is not a valid 204.
        """
        _require_card(session, card_id)
        return _price_response(PriceService(session).latest_price(card_id, variant))

    @app.post("/cards/{card_id}/prices/refresh")
    def refresh_price(
        card_id: str,
        variant: str = Query(default="normal"),
        session: Session = Depends(get_session),
        provider=Depends(get_price_provider),
    ) -> Response:
        """Fetch this card's price from the live source now.

        Measured 4.3 s mean and 9.1 s worst case, because the upstream API fails
        often and the client backs off. Callers must not block a scan on this.
        """
        _require_card(session, card_id)
        service = PriceService(session, provider)
        service.refresh_card(card_id)
        return _price_response(service.latest_price(card_id, variant))

    @app.post("/scans", response_model=ScanOut, status_code=201)
    async def record_scan(
        file: UploadFile = File(...),
        status: str = Query(...),
        predicted_card_id: str | None = Query(default=None),
        confidence: float | None = Query(default=None),
        visual_margin: float | None = Query(default=None),
        collector_number_read: str | None = Query(default=None),
        store: ScanStore = Depends(get_scan_store),
    ) -> ScanOut:
        scan = store.record(
            image_bytes=await file.read(),
            status=status,
            predicted_card_id=predicted_card_id,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
        )
        return _scan_out(scan)

    # Declared before /scans/{scan_id}: a literal path must be registered ahead of the
    # parameterised one, or "accuracy" is captured as a scan_id and fails to parse.
    @app.get("/scans/accuracy", response_model=ScanAccuracyOut)
    def scan_accuracy(store: ScanStore = Depends(get_scan_store)) -> ScanAccuracyOut:
        stats = store.accuracy()
        return ScanAccuracyOut(
            total=stats.total,
            answered=stats.answered,
            predicted=stats.predicted,
            correct=stats.correct,
            precision=stats.precision,
            coverage=stats.coverage,
            by_status=stats.by_status,
        )

    @app.get("/scans", response_model=list[ScanOut])
    def list_scans(
        limit: int = Query(default=50, le=200), store: ScanStore = Depends(get_scan_store)
    ) -> list[ScanOut]:
        return [_scan_out(s) for s in store.recent(limit)]

    @app.post("/scans/{scan_id}/confirm", response_model=ScanOut)
    def confirm_scan(scan_id: int, store: ScanStore = Depends(get_scan_store)) -> ScanOut:
        scan = store.confirm(scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="unknown scan")
        return _scan_out(scan)

    @app.post("/scans/{scan_id}/correct", response_model=ScanOut)
    def correct_scan(
        scan_id: int,
        card_id: str = Query(...),
        store: ScanStore = Depends(get_scan_store),
    ) -> ScanOut:
        try:
            scan = store.correct(scan_id, card_id)
        except ValueError as exc:
            # An id the catalog has never heard of is a client mistake, not a server
            # fault; without this it would surface as an opaque 500.
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if scan is None:
            raise HTTPException(status_code=404, detail="unknown scan")
        return _scan_out(scan)

    @app.post("/recognize", response_model=RecognizeOut)
    async def recognize(
        file: UploadFile = File(),
        variant: str = Query(default="normal"),
        rectify: bool = Query(default=True),
        session: Session = Depends(get_session),
        service=Depends(get_recognition_service),
    ) -> RecognizeOut:
        image = _decode_upload(await file.read())
        result = service.recognize(image, rectify=rectify)

        card = session.get(Card, result.card_id) if result.card_id else None
        price = (
            PriceService(session).latest_price(card.id, variant) if card is not None else None
        )
        return RecognizeOut(
            status=result.status,
            confidence=result.confidence,
            visual_margin=result.visual_margin,
            card=CardOut.from_card(card) if card is not None else None,
            price=_price_out(price) if price else None,
            candidates=_candidates_out(session, result.candidates),
            collector_number_read=result.ocr.collector_number,
        )

    @app.post("/collection", response_model=CollectionItemOut, status_code=201)
    def add_collection_item(
        payload: CollectionItemIn, session: Session = Depends(get_session)
    ) -> CollectionItemOut:
        store = CollectionStore(session)
        try:
            item = store.add(
                card_id=payload.card_id,
                variant=payload.variant,
                quantity=payload.quantity,
                acquired_price=payload.acquired_price,
                condition=payload.condition,
            )
        except ValueError as exc:
            # An id the catalog has never heard of is a client mistake, not a server
            # fault; without this it would surface as an opaque 500.
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _item_out(item)

    @app.get("/collection", response_model=list[CollectionItemOut])
    def list_collection(session: Session = Depends(get_session)) -> list[CollectionItemOut]:
        return [_item_out(item) for item in CollectionStore(session).list_items()]

    @app.get("/collection/valuation", response_model=ValuationOut)
    def collection_valuation(session: Session = Depends(get_session)) -> ValuationOut:
        valuation = CollectionStore(session).total_value()
        return ValuationOut(
            market_value=valuation.market_value,
            cost_basis=valuation.cost_basis,
            unrealized=valuation.unrealized,
            unpriced_items=valuation.unpriced_items,
        )

    return app


def _decode_upload(raw: bytes) -> Image.Image:
    """Turn uploaded bytes into an RGB image, or refuse them as a client error.

    A phone can post anything; a decode failure is a bad request, not a server fault.
    load() forces the decode here so a truncated file fails now rather than deep inside
    the pipeline as a 500.
    """
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail="upload could not be decoded as an image"
        ) from exc
    return image.convert("RGB")


def _candidates_out(session: Session, candidates) -> list[CandidateOut]:
    """Resolve candidate ids against the catalog, dropping any it does not know.

    RecognitionService already filters stale ids and logs them, so this should be a
    no-op — but the endpoint must not 500 if an index ever outruns the catalog.
    """
    if not candidates:
        return []
    cards = {
        card.id: card
        for card in session.scalars(
            select(Card).where(Card.id.in_([c.card_id for c in candidates]))
        ).all()
    }
    return [
        CandidateOut(
            card_id=candidate.card_id,
            name=cards[candidate.card_id].name,
            set_name=cards[candidate.card_id].card_set.name,
            number=cards[candidate.card_id].number,
            image_small=cards[candidate.card_id].image_small,
            visual_score=candidate.visual_score,
        )
        for candidate in candidates
        if candidate.card_id in cards
    ]


def _price_out(snapshot: PriceSnapshot) -> PriceOut:
    """Snapshot -> wire model, in one place.

    Every endpoint that returns a price goes through here so `source` and
    `source_updated_at` can never be dropped from one of them and not another.
    """
    return PriceOut.model_validate(snapshot, from_attributes=True)


def _price_response(snapshot: PriceSnapshot | None) -> Response:
    """A resolved price, or a bodiless 204 when the card is simply unpriced.

    Only 2 of 20,444 catalogued cards currently carry a price, so "no price" is the
    common case and must not read as an error. mode="json" because `fetched_at` is a
    datetime, which JSONResponse's encoder will not serialise on its own.
    """
    if snapshot is None:
        return Response(status_code=204)
    return JSONResponse(_price_out(snapshot).model_dump(mode="json"))


def _scan_out(scan: ScanLog) -> ScanOut:
    return ScanOut(
        id=scan.id,
        status=scan.status,
        predicted_card_id=scan.predicted_card_id,
        corrected_card_id=scan.corrected_card_id,
        confirmed=scan.confirmed,
        confidence=scan.confidence,
        visual_margin=scan.visual_margin,
        collector_number_read=scan.collector_number_read,
    )


def _require_card(session: Session, card_id: str) -> Card:
    card = session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"unknown card: {card_id!r}")
    return card


def _item_out(item: CollectionItem) -> CollectionItemOut:
    return CollectionItemOut(
        id=item.id,
        card_id=item.card_id,
        card_name=item.card.name,
        variant=item.variant,
        quantity=item.quantity,
        acquired_price=item.acquired_price,
        condition=item.condition,
    )


app = create_app()

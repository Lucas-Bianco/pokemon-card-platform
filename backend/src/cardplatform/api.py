"""HTTP read/write layer over the local catalog, prices, collection, and scans."""

from __future__ import annotations

import asyncio
import io
import logging
from datetime import datetime, timezone
from typing import Iterator

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cardplatform.alerts.api_models import (
    AlertEventOut,
    ListingOut,
    PushSubscribeIn,
    WatchCreate,
    WatchOut,
    WatchPatch,
)
from cardplatform.alerts.engine import AlertEngine
from cardplatform.alerts.notify import NotificationService
from cardplatform.collection.store import (
    Allocation,
    CollectionStore,
    Portfolio,
    PortfolioItem,
    PortfolioSummary,
)
from cardplatform.config import settings
from cardplatform.grading.centering import CenteringResult, psa_cap_for
from cardplatform.grading.store import GradingLabelStore
from cardplatform.grading.upside import GradingUpsideService
from cardplatform.db.models import (
    AlertEvent,
    Card,
    CollectionItem,
    GradingLabel,
    ListingSnapshot,
    PriceSnapshot,
    PushSubscription,
    ScanLog,
    Watch,
)
from cardplatform.db.session import Database
from cardplatform.prices.ebay_listings import EbayListingsProvider
from cardplatform.prices.listings_service import ListingsService
from cardplatform.prices.service import PriceService
from cardplatform.scans.store import ScanStore

_database: Database | None = None

log = logging.getLogger(__name__)

# Alert types the watchlist accepts on POST. Validation lives in the endpoint
# (not Pydantic) because the required-fields-per-type rule is conditional.
_ALERT_TYPES = {"restock", "new_listing", "price_target", "auction_ending", "drop_time"}


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


class CenteringOut(BaseModel):
    """A geometric measurement of the front border, reported as a ceiling.

    `psa_cap_range` is computed here rather than in the UI: naming the two grades a
    reading sits between requires PSA's threshold table, which belongs with the
    thresholds and not duplicated in a presentation component.
    """

    left_right: tuple[float, float]
    top_bottom: tuple[float, float]
    worst_axis: float
    uncertainty: float
    psa_cap: int | None
    psa_cap_certain: bool
    psa_cap_range: tuple[int, int] | None


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
    centering: CenteringOut | None
    # Phase 3b: the persisted rectified crop's relative path, surfaced so the
    # frontend can pass it back to /scans and record it on the scan_logs row.
    rectified_path: str | None = None


class ScanOut(BaseModel):
    id: int
    status: str
    predicted_card_id: str | None
    corrected_card_id: str | None
    confirmed: bool
    confidence: float | None
    visual_margin: float | None
    collector_number_read: str | None
    rectified_path: str | None = None
    variant: str | None = None


class ScanAccuracyOut(BaseModel):
    total: int
    answered: int
    predicted: int
    correct: int
    precision: float
    coverage: float
    by_status: dict[str, int]


class GradingLabelIn(BaseModel):
    """What a user sends back when they have graded a card in hand.

    `card_id` and `variant` are NOT accepted here: they are resolved from the
    scan (corrected_card_id over predicted_card_id; scan.variant as recorded).
    A label must describe the card the scan identified, not a card the caller
    types in — that would let the training set be poisoned with wishful ids.
    """

    grade: float
    grader: str
    cert_number: str | None = None
    notes: str | None = None


class GradingLabelOut(BaseModel):
    """A third-party grade attached to one scan.

    `variant` is nullable: a scan that never picked a variant carries an honest
    None, never a fabricated "normal". One label per scan — re-grading updates
    the same row, so `id` is stable across corrections.
    """

    id: int
    scan_id: int
    card_id: str
    variant: str | None
    grade: float
    grader: str
    cert_number: str | None
    notes: str | None
    created_at: datetime


class CollectionItemIn(BaseModel):
    card_id: str
    variant: str = "normal"
    quantity: int = Field(default=1, ge=1)
    acquired_price: float | None = None
    condition: str | None = None
    notes: str | None = None


class CollectionItemOut(BaseModel):
    id: int
    card_id: str
    card_name: str
    variant: str
    quantity: int
    acquired_price: float | None
    condition: str | None


class CollectionItemUpdate(BaseModel):
    """Partial update to a holding's purchase details. Every field is optional; a field
    that is absent (None) is left untouched, except acquired_price which is set
    unconditionally (pass None to clear a cost basis)."""

    acquired_price: float | None = None
    acquired_at: datetime | None = None
    condition: str | None = None
    notes: str | None = None


class PortfolioItemOut(BaseModel):
    id: int
    card_id: str
    card_name: str
    set_id: str
    set_name: str
    variant: str
    quantity: int
    acquired_price: float | None
    acquired_at: datetime | None
    condition: str | None
    notes: str | None
    market_price: float | None
    market_source: str | None
    market_source_updated_at: str | None
    unrealized: float | None
    priced: bool


class AllocationOut(BaseModel):
    set_id: str
    set_name: str
    market_value: float
    cost_basis: float
    item_count: int


class PortfolioSummaryOut(BaseModel):
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int
    priced_items: int
    allocation: list[AllocationOut]
    top_gainers: list[PortfolioItemOut]
    top_losers: list[PortfolioItemOut]


class PortfolioOut(BaseModel):
    summary: PortfolioSummaryOut
    items: list[PortfolioItemOut]


class PricePointOut(BaseModel):
    """One observed price in a history series. source and source_updated_at travel with
    every point so a chart never presents a number without saying where it came from."""

    fetched_at: datetime
    source: str
    variant: str
    market: float | None
    source_updated_at: str


class PriceHistoryOut(BaseModel):
    card_id: str
    variant: str
    points: list[PricePointOut]


class ValuationOut(BaseModel):
    market_value: float
    cost_basis: float
    unrealized: float
    unpriced_items: int


class GradingUpsideTierOut(BaseModel):
    """One tier of the grading spread (raw / psa9 / psa10), or null when unpriced.

    `market` may be null when the snapshot exists but carries no market figure, and
    the whole object is null when the underlying snapshot is missing — never a
    fabricated $0 (the project's sacred convention; see frontend PortfolioView.tsx
    and PriceChart.tsx, which render an em dash and "no market price" rather than
    a flat zero). `source` and `source_updated_at` travel with every figure so the
    UI can say where a number came from and how old it is.
    """

    market: float | None
    source: str
    source_updated_at: str


class GradingUpsideOut(BaseModel):
    """The raw-vs-graded price spread, NOT a grade prediction.

    `upside_to_10` is null unless BOTH raw_price and psa10 are present; a fabricated
    number from a missing input would be confidently-wrong. `graded_prices_unavailable`
    is true only when psa9 AND psa10 are both null, signalling the frontend to show
    "graded prices unavailable — set a graded-price provider key" instead of a
    misleading panel of zeroes.
    """

    card_id: str
    variant: str
    raw_price: GradingUpsideTierOut | None
    psa9: GradingUpsideTierOut | None
    psa10: GradingUpsideTierOut | None
    grading_fee: float
    upside_to_10: float | None
    graded_prices_unavailable: bool


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

    @app.get("/cards/{card_id}/prices/history", response_model=PriceHistoryOut)
    def card_price_history(
        card_id: str,
        variant: str = Query(default="normal"),
        days: int | None = Query(default=None, ge=1),
        session: Session = Depends(get_session),
    ) -> PriceHistoryOut:
        """The price series for one card and variant, oldest first.

        One point per source_updated_at, tcgplayer-preferred — the same resolution
        latest_price uses, so a chart line and the headline price agree on what 'the
        price' is. Each point carries its source and source_updated_at; the API never
        blends sources into one number. `days` windows the series to the last N days of
        observations.
        """
        _require_card(session, card_id)
        points = PriceService(session).price_history(card_id, variant, days=days)
        return PriceHistoryOut(
            card_id=card_id,
            variant=variant,
            points=[
                PricePointOut(
                    fetched_at=p.fetched_at,
                    source=p.source,
                    variant=p.variant,
                    market=p.market,
                    source_updated_at=p.source_updated_at,
                )
                for p in points
            ],
        )

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

    @app.get("/cards/{card_id}/grading-upside", response_model=GradingUpsideOut)
    def grading_upside(
        card_id: str,
        variant: str = Query(...),
        session: Session = Depends(get_session),
    ) -> GradingUpsideOut:
        """The grading-upside spread: raw price vs PSA-9 vs PSA-10 minus the grading fee.

        This is a PRICE SPREAD, NOT a grade prediction. It does not estimate
        P(PSA 10) for this card — that needs the grade predictor we don't have yet
        (Phase 3c). It answers the simpler honest question the user can already
        act on: given today's raw market price, today's PSA-9/10 market prices,
        and the bulk grading fee, what is the dollar upside to a PSA-10?

        `variant` is required because the raw price is variant-specific. Every
        price field is null when the underlying snapshot is missing, never a
        fabricated $0. `upside_to_10` is null unless BOTH raw and psa10 are
        present. Unknown card returns 404 (not an empty 200).
        """
        _require_card(session, card_id)
        return GradingUpsideOut(
            **GradingUpsideService(session).upside(card_id, variant)
        )

    @app.post("/scans", response_model=ScanOut, status_code=201)
    async def record_scan(
        file: UploadFile = File(...),
        status: str = Query(...),
        predicted_card_id: str | None = Query(default=None),
        confidence: float | None = Query(default=None),
        visual_margin: float | None = Query(default=None),
        collector_number_read: str | None = Query(default=None),
        rectified_path: str | None = Query(default=None),
        variant: str | None = Query(default=None),
        store: ScanStore = Depends(get_scan_store),
    ) -> ScanOut:
        scan = store.record(
            image_bytes=await file.read(),
            status=status,
            predicted_card_id=predicted_card_id,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
            rectified_path=rectified_path,
            variant=variant,
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

    @app.post("/scans/{scan_id}/grade-label", response_model=GradingLabelOut, status_code=201)
    def record_grade_label(
        scan_id: int,
        payload: GradingLabelIn,
        session: Session = Depends(get_session),
    ) -> GradingLabelOut:
        """Record the grade a user received back from PSA/CGC/BGS for this scan.

        This is the project's only honest source of labelled graded-card data —
        a phone photo the user actually mailed in and got a verdict on. The
        store resolves card_id/variant from the scan itself (never the request
        body) so the label always describes the card the scan identified.

        Upserts: re-grading the same scan updates the one existing row rather
        than inserting a second, so one scan yields one label.
        """
        store = GradingLabelStore(session)
        try:
            row = store.label(
                scan_id,
                grade=payload.grade,
                grader=payload.grader,
                cert_number=payload.cert_number,
                notes=payload.notes,
            )
        except ValueError as exc:
            # Bad grade/grader, or a scan that named no card: client mistake, 400.
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if row is None:
            raise HTTPException(status_code=404, detail="scan not found")
        return _grading_label_out(row)

    @app.get("/scans/{scan_id}/grade-label", response_model=GradingLabelOut)
    def get_grade_label(
        scan_id: int,
        session: Session = Depends(get_session),
    ) -> GradingLabelOut:
        """The label attached to a scan, or 404 if none.

        "No label yet" is the common case (most scans are never mailed in), but
        it is distinct from "the scan does not exist" — both read as 404 here
        rather than returning a bare null, matching how /scans/{id}/confirm
        treats an unknown scan.
        """
        row = GradingLabelStore(session).for_scan(scan_id)
        if row is None:
            raise HTTPException(status_code=404, detail="no grade label for this scan")
        return _grading_label_out(row)

    @app.get("/grading/labels", response_model=list[GradingLabelOut])
    def list_grade_labels(
        card_id: str | None = Query(default=None),
        grader: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> list[GradingLabelOut]:
        """Labels, newest first. Both filters optional; empty list if none.

        Never 404: an empty result set is a valid answer (nothing graded yet),
        not a missing resource. `grader` matches case-insensitively server-side
        via func.lower()==, never ilike.
        """
        rows = GradingLabelStore(session).list_labels(card_id=card_id, grader=grader)
        return [_grading_label_out(r) for r in rows]

    @app.post("/recognize", response_model=RecognizeOut)
    async def recognize(
        file: UploadFile = File(),
        variant: str = Query(default="normal"),
        rectify: bool = Query(default=True),
        corners: str | None = Query(default=None),
        session: Session = Depends(get_session),
        service=Depends(get_recognition_service),
    ) -> RecognizeOut:
        # Parsed before the decode so a malformed quad fails fast, and so a rejected
        # request never reaches the service.
        placed_corners = _parse_corners(corners)
        image = _decode_upload(await file.read())
        result, centering = service.recognize(
            image, rectify=rectify, corners=placed_corners
        )

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
            centering=_centering_out(centering) if centering is not None else None,
            rectified_path=result.rectified_path,
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
                notes=payload.notes,
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

    # Declared before PATCH /collection/{item_id}: a literal path must be registered
    # ahead of the parameterised one, or "portfolio" is captured as an item_id.
    @app.get("/collection/portfolio", response_model=PortfolioOut)
    def collection_portfolio(session: Session = Depends(get_session)) -> PortfolioOut:
        """Priced holdings plus a summary in one round trip.

        Per-item market_price/unrealized/priced are computed server-side via
        PriceService.latest_price — the frontend never resolves 'the latest price'
        itself. The summary carries allocation by set and top gainers/losers.
        """
        portfolio = CollectionStore(session).portfolio()
        return PortfolioOut(
            summary=_summary_out(portfolio.summary),
            items=[_portfolio_item_out(i) for i in portfolio.items],
        )

    @app.patch("/collection/{item_id}", response_model=CollectionItemOut)
    def patch_collection_item(
        item_id: int,
        payload: CollectionItemUpdate,
        session: Session = Depends(get_session),
    ) -> CollectionItemOut:
        """Backfill or correct a holding's purchase details (cost basis, acquired date,
        condition, notes) so portfolio P/L can be computed for items added before the
        scan flow started asking 'what you paid'."""
        store = CollectionStore(session)
        try:
            item = store.set_cost_basis(
                item_id,
                acquired_price=payload.acquired_price,
                acquired_at=payload.acquired_at,
                condition=payload.condition,
                notes=payload.notes,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return _item_out(item)

    @app.delete("/collection")
    def delete_collection_item(
        card_id: str = Query(...),
        variant: str = Query(...),
        quantity: int = Query(default=1, ge=1),
        session: Session = Depends(get_session),
    ) -> Response:
        """Remove copies of a holding. Removing more than held, or a card never held, is
        a no-op; clearing the row returns 204 either way."""
        CollectionStore(session).remove(card_id, variant=variant, quantity=quantity)
        return Response(status_code=204)

    # --------------------------------------------------------------- watchlist
    # Phase 3c: alert subscriptions. Filters are exact-match (card_id, active) —
    # the watchlist has no free-text search, so no ilike. Ordered newest first
    # (id desc), consistent with the grading-labels feed.
    @app.get("/watchlist", response_model=list[WatchOut])
    def list_watches(
        card_id: str | None = Query(default=None),
        active: bool | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> list[WatchOut]:
        stmt = select(Watch).order_by(Watch.id.desc())
        if card_id is not None:
            stmt = stmt.where(Watch.card_id == card_id)
        if active is not None:
            stmt = stmt.where(Watch.active == active)
        rows = session.scalars(stmt).all()
        return [WatchOut.model_validate(r) for r in rows]

    @app.post("/watchlist", response_model=WatchOut, status_code=201)
    def create_watch(
        payload: WatchCreate, session: Session = Depends(get_session)
    ) -> WatchOut:
        if payload.alert_type not in _ALERT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"alert_type must be one of {sorted(_ALERT_TYPES)}",
            )
        if payload.alert_type == "price_target" and payload.target_price is None:
            raise HTTPException(
                status_code=422,
                detail="target_price is required for alert_type 'price_target'",
            )
        if payload.alert_type == "drop_time" and payload.drop_at is None:
            raise HTTPException(
                status_code=422,
                detail="drop_at is required for alert_type 'drop_time'",
            )
        if payload.card_id is not None:
            _require_card(session, payload.card_id)
        watch = Watch(
            card_id=payload.card_id,
            subject_label=payload.subject_label,
            variant=payload.variant,
            alert_type=payload.alert_type,
            target_price=payload.target_price,
            drop_at=payload.drop_at,
            lead_time_min=payload.lead_time_min,
            auction_window_min=payload.auction_window_min,
            active=True,
        )
        session.add(watch)
        session.commit()
        session.refresh(watch)
        return WatchOut.model_validate(watch)

    @app.patch("/watchlist/{watch_id}", response_model=WatchOut)
    def patch_watch(
        watch_id: int,
        payload: WatchPatch,
        session: Session = Depends(get_session),
    ) -> WatchOut:
        watch = session.get(Watch, watch_id)
        if watch is None:
            raise HTTPException(status_code=404, detail="unknown watch")
        if payload.active is not None:
            watch.active = payload.active
        if payload.target_price is not None:
            watch.target_price = payload.target_price
        if payload.drop_at is not None:
            watch.drop_at = payload.drop_at
        if payload.lead_time_min is not None:
            watch.lead_time_min = payload.lead_time_min
        if payload.auction_window_min is not None:
            watch.auction_window_min = payload.auction_window_min
        session.commit()
        session.refresh(watch)
        return WatchOut.model_validate(watch)

    @app.delete("/watchlist/{watch_id}")
    def delete_watch(
        watch_id: int, session: Session = Depends(get_session)
    ) -> Response:
        watch = session.get(Watch, watch_id)
        if watch is None:
            raise HTTPException(status_code=404, detail="unknown watch")
        session.delete(watch)
        session.commit()
        return Response(status_code=204)

    # --------------------------------------------------------------- alerts feed
    # The engine fires AlertEvents in T3; this layer reads them and flips read_at.
    @app.get("/alerts", response_model=list[AlertEventOut])
    def list_alerts(
        unread: bool | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        session: Session = Depends(get_session),
    ) -> list[AlertEventOut]:
        stmt = select(AlertEvent).order_by(
            AlertEvent.created_at.desc(), AlertEvent.id.desc()
        ).limit(limit).offset(offset)
        if unread:
            stmt = stmt.where(AlertEvent.read_at.is_(None))
        rows = session.scalars(stmt).all()
        return [AlertEventOut.model_validate(r) for r in rows]

    # Declared before /alerts/{id}: a literal path must be registered ahead of
    # the parameterised one, or "read-all" / "unread-count" are captured as an id.
    @app.post("/alerts/read-all")
    def read_all_alerts(session: Session = Depends(get_session)) -> dict[str, int]:
        now = datetime.now(timezone.utc)
        rows = session.scalars(
            select(AlertEvent).where(AlertEvent.read_at.is_(None))
        ).all()
        for row in rows:
            row.read_at = now
        session.commit()
        return {"updated": len(rows)}

    @app.get("/alerts/unread-count")
    def alerts_unread_count(session: Session = Depends(get_session)) -> dict[str, int]:
        count = session.scalar(
            select(func.count(AlertEvent.id)).where(AlertEvent.read_at.is_(None))
        )
        return {"count": int(count or 0)}

    @app.patch("/alerts/{alert_id}", response_model=AlertEventOut)
    def mark_alert_read(
        alert_id: int, session: Session = Depends(get_session)
    ) -> AlertEventOut:
        event = session.get(AlertEvent, alert_id)
        if event is None:
            raise HTTPException(status_code=404, detail="unknown alert")
        event.read_at = datetime.now(timezone.utc)
        session.commit()
        session.refresh(event)
        return AlertEventOut.model_validate(event)

    # --------------------------------------------------------------- listings
    @app.post("/cards/{card_id}/listings")
    def refresh_card_listings(
        card_id: str,
        variant: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> dict:
        """Refresh + return the latest marketplace listings for this card.

        Honest empty state: when no `listings_api_key` is configured the provider
        returns [] WITHOUT touching the network, and `listings_unavailable` is
        True (no provider configured — never fake listings). When a provider IS
        configured but returns [] (e.g. eBay found nothing), `listings_unavailable`
        is False (the source was queried, just empty). Unknown card is 404.
        """
        _require_card(session, card_id)
        v = variant or ""
        service = ListingsService(session, EbayListingsProvider())
        service.refresh_listings(card_id, v)
        rows = service.latest_listings(card_id, v)
        return {
            "listings": [ListingOut.model_validate(r) for r in rows],
            "listings_unavailable": settings.listings_api_key is None,
        }

    # --------------------------------------------------------------- push
    @app.get("/push/vapid-public")
    def vapid_public() -> dict[str, str]:
        # Empty string = not configured (honest; frontend checks for emptiness,
        # never None — a keyless server is the default state, not an error).
        return {"public_key": settings.vapid_public_key or ""}

    @app.post("/push/subscribe", status_code=201)
    def push_subscribe(
        payload: PushSubscribeIn,
        session: Session = Depends(get_session),
    ) -> dict:
        existing = session.scalars(
            select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
        ).first()
        if existing is not None:
            existing.p256dh = payload.p256dh
            existing.auth = payload.auth
            session.commit()
            session.refresh(existing)
            return {"id": existing.id, "endpoint": existing.endpoint}
        sub = PushSubscription(
            endpoint=payload.endpoint, p256dh=payload.p256dh, auth=payload.auth
        )
        session.add(sub)
        session.commit()
        session.refresh(sub)
        return {"id": sub.id, "endpoint": sub.endpoint}

    @app.delete("/push/subscribe")
    def push_unsubscribe(
        endpoint: str = Query(...),
        session: Session = Depends(get_session),
    ) -> Response:
        sub = session.scalars(
            select(PushSubscription).where(PushSubscription.endpoint == endpoint)
        ).first()
        if sub is None:
            raise HTTPException(status_code=404, detail="unknown subscription")
        session.delete(sub)
        session.commit()
        return Response(status_code=204)

    # --------------------------------------------------------------- poll loop
    # In-process alert poll: one background task per app, started once on startup.
    # The CLI `check-alerts` is the durable cron path; this loop only runs while the
    # server is up and swallows per-tick exceptions so a bad tick never crashes the
    # server. The Database is constructed lazily INSIDE the loop (after the first
    # sleep) so importing the app / running TestClient never touches the real data
    # file — the first tick is `alert_poll_min` minutes away, which tests never
    # reach.
    poll_task: asyncio.Task | None = None

    @app.on_event("startup")
    async def _start_alert_poll_loop() -> None:
        nonlocal poll_task
        if settings.alert_poll_min <= 0:
            return

        async def _poll_loop() -> None:
            while True:
                await asyncio.sleep(settings.alert_poll_min * 60)
                try:
                    db = Database(settings)
                    db.create_all()
                    with db.session() as session:
                        engine = AlertEngine(
                            session,
                            ListingsService(session, EbayListingsProvider()),
                            NotificationService(session, settings),
                            settings,
                        )
                        engine.check_alerts()
                except Exception:
                    log.warning("alert poll tick failed", exc_info=True)

        poll_task = asyncio.create_task(_poll_loop())

    @app.on_event("shutdown")
    async def _stop_alert_poll_loop() -> None:
        if poll_task is not None and not poll_task.done():
            poll_task.cancel()

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


def _parse_corners(raw: str | None) -> list[tuple[float, float]] | None:
    """Parse "x1,y1,x2,y2,x3,y3,x4,y4" from the manual-adjust UI.

    Coordinates are in the source image's pixel space, because that is what the
    server rectifies against — the client converts from its own display scale.
    """
    if not raw:
        return None
    try:
        values = [float(part) for part in raw.split(",")]
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="corners must be numbers") from exc
    if len(values) != 8:
        raise HTTPException(status_code=422, detail="corners must be 8 numbers")
    return [(values[i], values[i + 1]) for i in range(0, 8, 2)]


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


def _psa_cap_range(centering: CenteringResult) -> tuple[int, int] | None:
    """The two grades an uncertain reading sits between, or None.

    Evaluated at both ends of the uncertainty interval. Note the direction: a LOWER
    worst_axis means BETTER centering, so the low end of the interval yields the
    HIGHER grade.

    Returns None when the cap is certain, when both ends agree, or when either end
    falls outside every published band — an unbounded range cannot be stated, and
    inventing a bound would be worse than saying nothing.
    """
    if centering.psa_cap_certain:
        return None
    better = psa_cap_for(centering.worst_axis - centering.uncertainty)
    worse = psa_cap_for(centering.worst_axis + centering.uncertainty)
    if better is None or worse is None or better == worse:
        return None
    return (min(better, worse), max(better, worse))


def _centering_out(centering: CenteringResult) -> CenteringOut:
    return CenteringOut(
        left_right=centering.left_right,
        top_bottom=centering.top_bottom,
        worst_axis=centering.worst_axis,
        uncertainty=centering.uncertainty,
        psa_cap=centering.psa_cap,
        psa_cap_certain=centering.psa_cap_certain,
        psa_cap_range=_psa_cap_range(centering),
    )


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
        rectified_path=scan.rectified_path,
        variant=scan.variant,
    )


def _grading_label_out(row: GradingLabel) -> GradingLabelOut:
    """GradingLabel -> wire model, in one place so variant's None survives.

    A scan that never picked a variant stores NULL and must surface NULL here,
    not a defaulted "normal" — the frontend distinguishes "no variant" from a
    chosen one, and a predictor trained on these labels must not read a
    fabricated variant.
    """
    return GradingLabelOut(
        id=row.id,
        scan_id=row.scan_id,
        card_id=row.card_id,
        variant=row.variant,
        grade=row.grade,
        grader=row.grader,
        cert_number=row.cert_number,
        notes=row.notes,
        created_at=row.created_at,
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


def _portfolio_item_out(item: PortfolioItem) -> PortfolioItemOut:
    return PortfolioItemOut(
        id=item.id,
        card_id=item.card_id,
        card_name=item.card_name,
        set_id=item.set_id,
        set_name=item.set_name,
        variant=item.variant,
        quantity=item.quantity,
        acquired_price=item.acquired_price,
        acquired_at=item.acquired_at,
        condition=item.condition,
        notes=item.notes,
        market_price=item.market_price,
        market_source=item.market_source,
        market_source_updated_at=item.market_source_updated_at,
        unrealized=item.unrealized,
        priced=item.priced,
    )


def _allocation_out(a: Allocation) -> AllocationOut:
    return AllocationOut(
        set_id=a.set_id,
        set_name=a.set_name,
        market_value=a.market_value,
        cost_basis=a.cost_basis,
        item_count=a.item_count,
    )


def _summary_out(s: PortfolioSummary) -> PortfolioSummaryOut:
    return PortfolioSummaryOut(
        market_value=s.market_value,
        cost_basis=s.cost_basis,
        unrealized=s.unrealized,
        unpriced_items=s.unpriced_items,
        priced_items=s.priced_items,
        allocation=[_allocation_out(a) for a in s.allocation],
        top_gainers=[_portfolio_item_out(i) for i in s.top_gainers],
        top_losers=[_portfolio_item_out(i) for i in s.top_losers],
    )


app = create_app()

"""HTTP read/write layer over the local catalog, prices, collection, and scans."""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
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
from cardplatform.deals.api_models import (
    DealAssessmentOut,
    DealsResponse,
    ThresholdsOut,
)
from cardplatform.deals.engine import DealEngine
from cardplatform.collection.store import (
    Allocation,
    CollectionStore,
    Portfolio,
    PortfolioItem,
    PortfolioSummary,
)
from cardplatform.config import settings
from cardplatform.catalog.api_models import (
    ChecklistEntryOut,
    CompletionSummaryOut,
    SetCompletionOut,
    SetProgressOut,
)
from cardplatform.catalog.completion import CompletionService
from cardplatform.authenticity.checklist import checklist_for
from cardplatform.authenticity.consistency import check_consistency
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
from cardplatform.prices import sold_comps_api_models as sold_models
from cardplatform.prices.ebay_listings import EbayListingsProvider, parse_ebay_item_id
from cardplatform.prices.listings_service import ListingsService
from cardplatform.prices.service import PriceService
from cardplatform.recognition import detectors
from cardplatform.scans.store import ScanStore
from cardplatform.sealed.api_models import (
    SealedDealAssessmentOut,
    SealedDealsResponse,
    SealedLedgerEntryOut,
    SealedLedgerResponse,
    SealedPricePointOut,
    SealedProductMarketOut,
    SealedProductOut,
    SealedProductsResponse,
    SealedPurchaseIn,
    SealedPurchaseOut,
    SealedScanLogIn,
    SealedSoldCompOut,
    SealedSoldCompsResponse,
    SealedThresholdsOut,
    SheetsSyncResultOut,
    ValuationRefreshResultOut,
)
from cardplatform.sealed.catalog_service import (
    PRINT_STATUSES,
    PRODUCT_TYPES,
    SealedCatalogService,
)
from cardplatform.sealed.engine import SealedDealEngine
from cardplatform.sealed.ledger import LedgerService
from cardplatform.sealed.msrp_vs_market import MsrpVsMarketService
from cardplatform.sealed.scan_log import SealedScanLogService
from cardplatform.sealed.seed_data import SEALED_PRODUCTS
from cardplatform.cards.lookup import CardLookupService
from cardplatform.shop.assess import ShopAssessor
from cardplatform.shop.api_models import ShopAssessmentOut

_database: Database | None = None

log = logging.getLogger(__name__)

# Alert types the watchlist accepts on POST. Validation lives in the endpoint
# (not Pydantic) because the required-fields-per-type rule is conditional.
_ALERT_TYPES = {"restock", "new_listing", "price_target", "auction_ending", "drop_time", "deal"}


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
        # Phase A: seed the sealed-product catalog once when the table is empty.
        # Idempotent + never deletes/updates (never-delete discipline) — the catalog
        # is reference data the user may have edited; a re-run must not clobber it.
        # Cheap: one COUNT per process startup, only inserts on a truly empty table.
        with database.session() as session:
            svc = SealedCatalogService(session)
            if svc.count() == 0:
                svc.ensure_seed(SEALED_PRODUCTS)
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


class CardLookupItemOut(BaseModel):
    """One card match for the Prices tab's name -> price lookup (Phase D).

    `market` is the latest snapshot's market figure, or None when no snapshot exists
    (honest "no market price", never a fabricated 0). `source` + `source_updated_at`
    travel with the figure so the UI can say where it came from and how stale it is;
    both are None for an unpriced card. The empty-string `source_updated_at` sentinel
    is coerced to None on the wire (a missing stamp means "no timestamp", not "")."""

    card_id: str
    name: str
    set_id: str
    set_name: str
    number: str
    rarity: str | None
    image_small: str | None
    image_large: str | None
    market: float | None
    source: str | None
    source_updated_at: str | None


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


class BatchRecognizeOut(BaseModel):
    """One binder-page photo → N independent scan verdicts (Phase 4).

    Each result carries its own status/price/rectified_path; the batch_id groups
    them so the client can thread it back through POST /scans per card. Per-card
    statuses are NEVER collapsed into one batch status — that would fabricate
    confidence across cards that may each have recognised differently.
    """

    batch_id: str
    count: int
    results: list[RecognizeOut]


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
    # NULL on a single-card scan (a singleton batch); set for the N cards of one
    # bulk-cataloger photo, so a client can see the grouping actually landed.
    batch_id: str | None = None
    batch_index: int | None = None


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


class ConsistencyOut(BaseModel):
    """The one honest authenticity auto-signal: printed number vs catalog number.

    ``match`` is one of match / mismatch / unread / no_card (see
    authenticity.consistency). ``note`` is the honest explanation surfaced to
    the user — never a fake/real verdict. A mismatch is explicitly framed as
    "wrong recognition OR counterfeit, indistinguishable", because the project
    has zero confirmed-counterfeit samples to calibrate against.
    """

    printed_number: str | None
    catalog_number: str | None
    card_id: str | None
    card_name: str | None
    match: str
    note: str


class ChecklistItemOut(BaseModel):
    """One user-driven physical check. ``applies`` is False when the check is
    irrelevant to the card type (e.g. the holo light test for a non-holo card);
    the UI renders those as N/A, not hidden."""

    id: str
    title: str
    what_to_check: str
    caveat: str
    applies: bool


class AuthenticityOut(BaseModel):
    """The honest counterfeit tool: one measurable auto-signal + a transparent
    physical checklist. ``caveat`` is the banner stating this is a guide, not a
    verdict, and that no confirmed-counterfeit samples exist to calibrate it."""

    caveat: str
    consistency: ConsistencyOut
    checklist: list[ChecklistItemOut]


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

    @app.get("/cards/lookup", response_model=list[CardLookupItemOut])
    def lookup_cards(
        q: str = Query(min_length=2),
        limit: int = Query(default=20, ge=1, le=50),
        session: Session = Depends(get_session),
    ) -> list[CardLookupItemOut]:
        # Prices tab: type a name -> see matches with their latest market price.
        # min_length=2 gives a clean 422 for blank/1-char queries (the service is
        # safe to call directly but the route is the public boundary). Mirrors
        # search_cards' func.lower().like() pattern (NOT ilike — SQLite ASCII-only).
        service = CardLookupService(session, PriceService(session))
        return [CardLookupItemOut.model_validate(item) for item in service.lookup(q, limit)]

    @app.get("/sets", response_model=list[SetProgressOut])
    def list_sets(
        q: str | None = Query(default=None, min_length=1),
        limit: int = Query(default=50, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> list[SetProgressOut]:
        # Whitespace-only q is blank, not a search — 422 (mirrors the sealed-deals
        # contract). FastAPI's min_length counts whitespace, so we guard explicitly.
        if q is not None and not q.strip():
            raise HTTPException(status_code=422, detail="q must not be blank")
        service = CompletionService(session, PriceService(session))
        sets = service.list_sets(query=q)
        return [SetProgressOut.model_validate(s) for s in sets[:limit]]

    @app.get("/sets/{set_id}", response_model=SetCompletionOut)
    def get_set(set_id: str, session: Session = Depends(get_session)) -> SetCompletionOut:
        service = CompletionService(session, PriceService(session))
        try:
            detail = service.set_detail(set_id)
        except LookupError:
            raise HTTPException(status_code=404, detail=f"unknown set: {set_id!r}")
        return SetCompletionOut.model_validate(detail)

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
        batch_id: str | None = Query(default=None),
        batch_index: int | None = Query(default=None, ge=0),
        store: ScanStore = Depends(get_scan_store),
    ) -> ScanOut:
        """Log one recognition attempt against the photo it came from.

        `batch_id`/`batch_index` group the N cards of one bulk-cataloger photo.
        The client has always sent them; until they were declared here FastAPI
        discarded them silently, so every bulk card landed as its own singleton
        batch and a 9-card binder photo counted nine times in
        `GET /scans/accuracy`. Accepting them restores the batch-aware count
        `ScanStore.accuracy()` was written for. Both stay optional: a
        single-card scan omits them and stores NULL, as before.
        """
        scan = store.record(
            image_bytes=await file.read(),
            status=status,
            predicted_card_id=predicted_card_id,
            confidence=confidence,
            visual_margin=visual_margin,
            collector_number_read=collector_number_read,
            rectified_path=rectified_path,
            variant=variant,
            batch_id=batch_id,
            batch_index=batch_index,
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

    @app.get("/scans/{scan_id}/authenticity", response_model=AuthenticityOut)
    def scan_authenticity(
        scan_id: int,
        session: Session = Depends(get_session),
    ) -> AuthenticityOut:
        """The honest counterfeit tool for one scan: catalog-consistency auto-check
        + a user-driven physical checklist. Never a fake/real verdict.

        The consistency check resolves the card honestly from the scan
        (corrected_card_id wins over predicted_card_id; an orphaned id whose Card
        row is gone reads as no_card, not a fabricated number). The checklist is
        rarity-gated (the holo light test applies only to holo cards); the baseline
        scans carry no ``variant``, so rarity is the working signal.

        Even a not_found scan returns 200 with the checklist — the physical checks
        still apply to a card the pipeline failed to recognize — and an honest
        ``no_card`` consistency result, not a 404.
        """
        scan = session.get(ScanLog, scan_id)
        if scan is None:
            raise HTTPException(status_code=404, detail="unknown scan")

        resolved_id = scan.corrected_card_id or scan.predicted_card_id
        card = session.get(Card, resolved_id) if resolved_id is not None else None

        result = check_consistency(
            ocr_number=scan.collector_number_read,
            card_number=card.number if card is not None else None,
            card_id=card.id if card is not None else None,
            card_name=card.name if card is not None else None,
        )
        items = checklist_for(
            rarity=card.rarity if card is not None else None,
            variant=scan.variant,
        )

        return AuthenticityOut(
            caveat=(
                "A guide for what to check, not a verdict. The project has zero "
                "confirmed-counterfeit samples, so these checks are not calibrated "
                "against any known fakes. The one automatic check (printed number vs "
                "catalog) only flags a mismatch, which a wrong recognition can also cause."
            ),
            consistency=ConsistencyOut(
                printed_number=result.printed_number,
                catalog_number=result.catalog_number,
                card_id=result.card_id,
                card_name=result.card_name,
                match=result.match,
                note=result.note,
            ),
            checklist=[
                ChecklistItemOut(
                    id=i.id,
                    title=i.title,
                    what_to_check=i.what_to_check,
                    caveat=i.caveat,
                    applies=i.applies,
                )
                for i in items
            ],
        )

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

    @app.post("/recognize/batch", response_model=BatchRecognizeOut)
    async def recognize_batch(
        file: UploadFile = File(...),
        variant: str = Query(default="normal"),
        max_cards: int = Query(default=9, ge=1, le=18),
        session: Session = Depends(get_session),
        service=Depends(get_recognition_service),
    ) -> BatchRecognizeOut:
        """Detect every card in one binder-page photo, recognise each, price each.

        Additive to POST /recognize (unchanged): detect once via detect_all_quads
        (largest-area first), cap to max_cards, recognise_many, then resolve a
        price per CONFIDENT card via PriceService.latest_price — the only
        sanctioned price path. A not_found card returns card=None, price=None
        (never $0, never fabricated). This endpoint reads + recognises + prices
        only; it does NOT write ScanLog (preserving the recognise/log split).
        The client logs each card via POST /scans, threading batch_id back.
        """
        image = _decode_upload(await file.read())
        # Reference through the module so tests can monkeypatch
        # cardplatform.recognition.detectors.detect_all_quads.
        quads = detectors.detect_all_quads(image)
        if not quads:
            return BatchRecognizeOut(batch_id=uuid.uuid4().hex, count=0, results=[])
        # detect_all_quads returns largest-area first; clamp to the cap.
        quads = quads[:max_cards]
        recognized = service.recognize_many(image, [q for _, q in quads])
        price_service = PriceService(session)
        out_results: list[RecognizeOut] = []
        for _, result, centering in recognized:
            card = session.get(Card, result.card_id) if result.card_id else None
            price = (
                price_service.latest_price(card.id, variant)
                if card is not None
                else None
            )
            out_results.append(
                RecognizeOut(
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
            )
        return BatchRecognizeOut(
            batch_id=uuid.uuid4().hex, count=len(out_results), results=out_results
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
        if payload.alert_type == "deal" and payload.card_id is None:
            raise HTTPException(
                status_code=422,
                detail="card_id is required for alert_type 'deal'",
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
        service = ListingsService(session, EbayListingsProvider(catalog=_catalog_lookup(session)))
        service.refresh_listings(card_id, v)
        rows = service.latest_listings(card_id, v)
        return {
            "listings": [ListingOut.model_validate(r) for r in rows],
            "listings_unavailable": settings.listings_api_key is None,
        }

    # --------------------------------------------------------------- deals
    @app.get("/cards/{card_id}/deals", response_model=DealsResponse)
    def card_deals(
        card_id: str,
        variant: str | None = Query(default=None),
        session: Session = Depends(get_session),
    ) -> DealsResponse:
        """Rip-vs-flip deals for one card. Honest empty states: when no
        `listings_api_key` is configured, `listings_unavailable` is True (no
        provider configured — never fake listings); when a key IS set but no
        listings exist, `listings_empty` is True (the source was queried, just
        empty). Missing raw/graded inputs null the edge they feed — never a
        fabricated $0. Unknown card is 404 (not an empty 200).

        Deals are derived from the newest snapshots each call via the
        read-only DealEngine; this endpoint writes nothing and never resolves
        prices ad-hoc.
        """
        _require_card(session, card_id)
        v = variant or ""
        engine = DealEngine(session, settings)
        assessments = engine.assess(card_id, v)
        return DealsResponse(
            card_id=card_id,
            variant=v or None,
            listings_unavailable=settings.listings_api_key is None,
            listings_empty=(settings.listings_api_key is not None and not assessments),
            deals=[_deal_out(a) for a in assessments],
            thresholds=ThresholdsOut(
                deal_rip_min_abs=settings.deal_rip_min_abs,
                deal_rip_min_pct=settings.deal_rip_min_pct,
                deal_flip_min_abs=settings.deal_flip_min_abs,
            ),
        )

    @app.get("/deals", response_model=DealsResponse)
    def deals_feed(
        card_ids: str | None = Query(default=None),
        limit: int = Query(default=20, ge=1, le=100),
        session: Session = Depends(get_session),
    ) -> DealsResponse:
        """Cross-card deal feed. `card_ids` (CSV) defaults to the user's active
        watched cards. Assesses each with the empty variant (the common case for
        raw listings), merges, ranks by deal_score desc (nulls last), and
        truncates to `limit`.

        Honest per-card flags merge into the overall flags:
        `listings_unavailable` is True only when NO key is configured at all
        (no card could have queried a source); `listings_empty` is True when a
        key IS set but none of the assessed cards had listings.
        """
        if card_ids:
            ids: list[str] = [c.strip() for c in card_ids.split(",") if c.strip()]
        else:
            rows = session.scalars(
                select(Watch.card_id).where(
                    Watch.active.is_(True), Watch.card_id.is_not(None)
                )
            ).all()
            ids = sorted({r for r in rows})
        engine = DealEngine(session, settings)
        merged: list = []
        any_key = settings.listings_api_key is not None
        any_listing = False
        for cid in ids:
            assessments = engine.assess(cid, "")
            if assessments:
                any_listing = True
            merged.extend(assessments)
        merged.sort(key=lambda a: (a.deal_score is None, -(a.deal_score or 0.0)))
        return DealsResponse(
            card_id=None,
            variant=None,
            listings_unavailable=not any_key,
            listings_empty=any_key and not any_listing,
            deals=[_deal_out(a) for a in merged[:limit]],
            thresholds=ThresholdsOut(
                deal_rip_min_abs=settings.deal_rip_min_abs,
                deal_rip_min_pct=settings.deal_rip_min_pct,
                deal_flip_min_abs=settings.deal_flip_min_abs,
            ),
        )

    # --------------------------------------------------------------- sealed deals
    @app.get("/sealed/deals", response_model=SealedDealsResponse)
    def sealed_deals_feed(
        q: str = Query(
            ..., min_length=2,
            description="Sealed product search, e.g. 'scarlet violet booster box'",
        ),
        limit: int = Query(20, ge=1, le=50),
    ) -> SealedDealsResponse:
        """Ranked flip-edge deals for a sealed-product free-text query (Phase 05c).

        Sealed products (booster boxes, ETBs, collection boxes, packs) are queried on eBay
        via the same Finding API + App ID as listings — no separate key. Honest empty
        states: no key -> listings_unavailable/comps_unavailable; key set but no listings
        -> listings_empty; no sold comps -> sealed_market null -> every flip_edge null
        (never $0). Read-only: no snapshot writes, no DB session. Rip EV (opening for
        expected pull value) is deferred — needs pull-rate data we don't have.
        """
        q = q.strip()
        if not q or len(q) < 2:
            raise HTTPException(
                status_code=422, detail="query must be at least 2 non-space chars",
            )
        provider = EbayListingsProvider(settings)
        engine = SealedDealEngine(provider, settings=settings)
        result = engine.assess(q, limit=limit)
        key_set = bool(settings.listings_api_key)
        return SealedDealsResponse(
            query=q,
            limit=limit,
            listings_unavailable=not key_set,
            listings_empty=key_set and result.listings_count == 0,
            comps_unavailable=not key_set,
            comps_empty=key_set and result.comps_count == 0,
            sealed_market=(
                SealedPricePointOut.model_validate(result.sealed_market)
                if result.sealed_market is not None else None
            ),
            deals=[SealedDealAssessmentOut.model_validate(a) for a in result.assessments],
            thresholds=SealedThresholdsOut(
                sealed_flip_min_abs=settings.sealed_flip_min_abs,
                sealed_flip_min_pct=settings.sealed_flip_min_pct,
            ),
        )

    # --------------------------------------------------------------- sealed proof of sales (16)
    @app.get("/sealed/sold-comps", response_model=SealedSoldCompsResponse)
    def sealed_sold_comps(
        q: str = Query(
            ..., min_length=2,
            description="Sealed product search, e.g. 'scarlet violet booster box'",
        ),
        limit: int = Query(6, ge=1, le=10),
    ) -> SealedSoldCompsResponse:
        """Proven sales for a sealed-product free-text query (roadmap row 16).

        The individual recently-sold eBay listings behind the median `sealed_market`
        shown on /sealed/deals — actual transactions (date/price/condition/title/link),
        not a listed estimate. This is the project's honest differentiator: "99% of
        price apps assert a number and never prove anyone paid it." We prove it, or we
        honestly say we can't. Reuses `fetch_sold_listings_by_query` (same EndedWithSales
        gate as card sold-comps — only confirmed sales, never fabricated). On-demand
        evidence: no snapshot writes, no DB session. Honest empty flags mirror the
        established pattern: no key -> sold_comps_unavailable; key set, 0 sales ->
        sold_comps_empty (never $0).
        """
        q = q.strip()
        if not q or len(q) < 2:
            raise HTTPException(
                status_code=422, detail="query must be at least 2 non-space chars",
            )
        provider = EbayListingsProvider(settings)
        comps = provider.fetch_sold_listings_by_query(q, limit=limit)
        key_set = bool(settings.listings_api_key)
        return SealedSoldCompsResponse(
            query=q,
            limit=limit,
            sold_comps=[SealedSoldCompOut.model_validate(c) for c in comps],
            sold_comps_unavailable=not key_set,
            sold_comps_empty=key_set and not comps,
        )

    # --------------------------------------------------------------- shop assistant (Phase E)
    @app.get("/shop/assess", response_model=ShopAssessmentOut)
    def shop_assess(
        url: str = Query(
            ..., min_length=8,
            description="Full eBay listing URL, e.g. https://www.ebay.com/itm/123456789012",
        ),
        limit: int = Query(6, ge=1, le=10),
        session: Session = Depends(get_session),
    ) -> ShopAssessmentOut:
        """Assess a single eBay listing by URL (roadmap row 13 / Phase E).

        Paste a listing URL -> parse the item ID -> fetch the live listing via the
        Finding API getSingleItem (same App ID auth, no OAuth) -> match the title to
        a sealed product (high confidence, curated catalog) or a card (low confidence,
        best-effort) -> deal verdict against the proven market (sold-comps median for
        sealed, latest_price for cards) -> for card matches, the Phase 07 authenticity
        guide (printed-number consistency + rarity-gated checklist; never a fake/real
        verdict). Composes three existing pillars (deal sniper / flip-edge, price +
        sold-comps, authenticity) into one read. Read-only: no data/ writes, no new
        tables, no snapshot persistence. Honest empty states mirror the rest of the
        app: no key -> listing_unavailable; key set, not found -> listing_not_found;
        no market -> edge null (never $0); no match -> deal None. A 422 is returned
        when the URL is not an eBay listing URL (parse_ebay_item_id returns None).
        """
        item_id = parse_ebay_item_id(url)
        if item_id is None:
            raise HTTPException(
                status_code=422,
                detail="url must be an eBay listing URL like https://www.ebay.com/itm/<id>",
            )
        provider = EbayListingsProvider(settings)
        assessor = ShopAssessor(session, settings, provider)
        assessment = assessor.assess(url, limit=limit)
        return ShopAssessmentOut.model_validate(assessment)

    # --------------------------------------------------------------- sealed catalog (Phase A)
    @app.get("/sealed/products", response_model=SealedProductsResponse)
    def sealed_products(
        q: str | None = Query(
            None,
            description="Optional case-insensitive substring on name or era",
        ),
        type: str | None = Query(
            None,
            description=f"Filter by product_type; one of {PRODUCT_TYPES}",
        ),
        status: str | None = Query(
            None,
            description=f"Filter by print_status; one of {PRINT_STATUSES}",
        ),
        limit: int = Query(50, ge=1, le=200),
        session: Session = Depends(get_session),
    ) -> SealedProductsResponse:
        """Browse/search the sealed-product reference catalog (Phase A, roadmap row 09).

        Curated in-repo seed (NOT magic auto-update — no official sealed-product API
        exists; a future semi-automated community sync with manual review is a
        documented follow-up). `msrp` is nullable — many products have no official US
        MSRP (booster boxes, premiums); the UI shows "no MSRP", never `$0`. Filters
        compose with AND; no query/filters lists newest first. `type`/`status` are
        validated against the allowed sets (422 on an unknown value).
        """
        if type is not None and type not in PRODUCT_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"type must be one of {PRODUCT_TYPES}",
            )
        if status is not None and status not in PRINT_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"status must be one of {PRINT_STATUSES}",
            )
        svc = SealedCatalogService(session)
        products = svc.search(query=q, product_type=type, print_status=status, limit=limit)
        return SealedProductsResponse(
            products=[SealedProductOut.model_validate(p) for p in products],
            count=len(products),
            product_type=type,
            print_status=status,
        )

    @app.get("/sealed/products/{slug}", response_model=SealedProductOut)
    def sealed_product(slug: str, session: Session = Depends(get_session)) -> SealedProductOut:
        """One sealed-product catalog row by slug. Unknown slug -> 404 (honest, never
        a fabricated blank row)."""
        svc = SealedCatalogService(session)
        try:
            product = svc.get(slug)
        except LookupError:
            raise HTTPException(status_code=404, detail="sealed product not found")
        return SealedProductOut.model_validate(product)

    @app.get("/sealed/products/{slug}/market", response_model=SealedProductMarketOut)
    def sealed_product_market(
        slug: str, session: Session = Depends(get_session)
    ) -> SealedProductMarketOut:
        """One catalog product's curated MSRP vs its live sold-comps median (Phase C).

        Read-only: no `data/` writes. The provider call is the same one
        /sealed/sold-comps uses, so the market figure here is exactly the figure
        proven there. Unknown slug -> 404. The service degrades to [] on any
        provider failure (never raises out of a provider call), so the honest
        unavailable/empty flags reach the wire even when eBay is down.
        """
        provider = EbayListingsProvider(settings)
        svc = MsrpVsMarketService(session, settings, provider)
        try:
            result = svc.compare(slug)
        except LookupError:
            raise HTTPException(status_code=404, detail="sealed product not found")
        return SealedProductMarketOut.model_validate(result)

    # --------------------------------------------------------------- sealed ledger (05d)
    @app.get("/sealed/ledger", response_model=SealedLedgerResponse)
    def sealed_ledger(session: Session = Depends(get_session)) -> SealedLedgerResponse:
        """Full reseller ledger — purchases joined with latest valuation + read-only profit.

        Read-only DB view; the provider is constructed but not called here (refresh_* is the
        only write path). `listings_unavailable` is the honest banner: True when no
        `listings_api_key` is configured (sealed reuses the eBay listings key), so the
        front-end never shows fabricated $0 valuations.
        """
        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        entries = svc.list_ledger()
        return SealedLedgerResponse(
            purchases=[SealedLedgerEntryOut.model_validate(e) for e in entries],
            listings_unavailable=not bool(settings.listings_api_key),
        )

    @app.post("/sealed/ledger", response_model=SealedPurchaseOut, status_code=201)
    def create_sealed_purchase(
        payload: SealedPurchaseIn, session: Session = Depends(get_session)
    ) -> SealedPurchaseOut:
        """Log a sealed-product buy. Pydantic bounds catch the obvious client mistakes; the
        LedgerService also validates and raises ValueError -> 422 (not a 500)."""
        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        try:
            p = svc.create_purchase(
                query=payload.query,
                product_type=payload.product_type,
                quantity=payload.quantity,
                cost_per_unit=payload.cost_per_unit,
                source=payload.source,
                listing_url=payload.listing_url,
                notes=payload.notes,
                bought_at=payload.bought_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SealedPurchaseOut.model_validate(p)

    @app.post("/sealed/ledger/from-catalog", response_model=SealedPurchaseOut, status_code=201)
    def create_sealed_purchase_from_catalog(
        payload: SealedScanLogIn, session: Session = Depends(get_session)
    ) -> SealedPurchaseOut:
        """Log a sealed-product buy straight from a catalog row, by slug (Phase B).

        The product's name + product_type are resolved server-side from the catalog,
        so the client only sends the slug + the purchase facts. Unknown slug ->
        LookupError -> 404; bad quantity/cost -> ValueError -> 422 (not a 500).
        Registered BEFORE the {purchase_id} route so FastAPI matches the static
        path first (mirrors /sealed/ledger/valuate's ordering note)."""
        svc = SealedScanLogService(session)
        try:
            p = svc.log_from_catalog(
                payload.slug,
                quantity=payload.quantity,
                cost_per_unit=payload.cost_per_unit,
                source=payload.source,
                listing_url=payload.listing_url,
                notes=payload.notes,
                bought_at=payload.bought_at,
            )
        except LookupError:
            raise HTTPException(status_code=404, detail="sealed product not found")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return SealedPurchaseOut.model_validate(p)

    @app.delete("/sealed/ledger/{purchase_id}")
    def delete_sealed_purchase(
        purchase_id: int, session: Session = Depends(get_session)
    ) -> Response:
        """Remove a purchase + its append-only valuations (explicit cascade — don't rely on
        a SQLite FK-cascade pragma). 404 on unknown, 204 on success."""
        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        if not svc.delete_purchase(purchase_id):
            raise HTTPException(status_code=404, detail="unknown purchase")
        return Response(status_code=204)

    @app.post("/sealed/ledger/valuate", response_model=ValuationRefreshResultOut)
    def valuate_sealed_ledger(session: Session = Depends(get_session)) -> ValuationRefreshResultOut:
        """Refresh the latest market snapshot for every purchase (append-only inserts).
        `skipped_no_key` is True only when the key was missing AND nothing was valued — an
        honest diagnostic, not a blanket flag. Registered BEFORE the {purchase_id} route so
        FastAPI matches the static path first."""
        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        return ValuationRefreshResultOut.model_validate(svc.refresh_all())

    @app.post("/sealed/ledger/sync", response_model=SheetsSyncResultOut)
    def sync_sealed_ledger(session: Session = Depends(get_session)) -> SheetsSyncResultOut:
        """Push the full ledger to a Google Sheet (full-tab overwrite, idempotent).

        Honest empty state: when OAuth/sheet aren't configured the client returns
        `synced=False, reason="not_configured"` WITHOUT a network call or raise — the
        front-end shows the not-configured banner instead of a failed sync. A configured
        sync clears the tab range then writes header + rows, so the sheet mirrors the
        ledger's current truth (edits/deletes included). Registered BEFORE the
        {purchase_id} route so FastAPI matches the static path first.
        """
        from cardplatform.sealed.ledger import build_sheet_rows
        from cardplatform.sealed.sheets import GoogleSheetsClient

        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        rows = build_sheet_rows(svc.list_ledger())
        result = GoogleSheetsClient(settings).sync(rows)
        return SheetsSyncResultOut(
            synced=result.synced, rows=result.rows, reason=result.reason
        )

    @app.post("/sealed/ledger/{purchase_id}/valuate", response_model=SealedLedgerEntryOut)
    def valuate_one_sealed_purchase(
        purchase_id: int, session: Session = Depends(get_session)
    ) -> SealedLedgerEntryOut:
        """Refresh the valuation for a single purchase and return the refreshed ledger row.
        404 on unknown purchase. Registered AFTER the static `/valuate` route to avoid
        shadowing it via the {purchase_id} path param."""
        provider = EbayListingsProvider(settings)
        svc = LedgerService(session, provider=provider, settings=settings)
        if svc.get_purchase(purchase_id) is None:
            raise HTTPException(status_code=404, detail="unknown purchase")
        svc.refresh_valuation(purchase_id)
        entries = svc.list_ledger()
        entry = next((e for e in entries if e.id == purchase_id), None)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown purchase")
        return SealedLedgerEntryOut.model_validate(entry)

    @app.get("/cards/{card_id}/sold-comps", response_model=sold_models.SoldCompsResponse)
    def card_sold_comps(
        card_id: str,
        variant: str | None = Query(default=None),
        limit: int = Query(default=3, ge=1),
        session: Session = Depends(get_session),
    ) -> sold_models.SoldCompsResponse:
        """Recent eBay *sold* listings for a card — sale evidence backing the
        raw market price ("market $120 because these 3 just sold at
        $118/$121/$119"). Honest flags: `sold_comps_unavailable` is True when
        no `listings_api_key` is configured (no provider); `sold_comps_empty`
        is True when a key IS set but eBay returned no sold comps. On-demand
        read — sold comps are NEVER persisted (no snapshot writes). Unknown
        card is 404.

        Backed by the deprecated findCompletedItems (still functional for free
        App IDs; degrades to [] if retired). Sold comps are evidence, not a
        price target.
        """
        _require_card(session, card_id)
        v = variant or ""
        limit = min(limit, 10)  # clamp to max 10
        provider = EbayListingsProvider(catalog=_catalog_lookup(session))
        comps = provider.fetch_sold_listings(card_id, v, limit=limit)
        unavailable = settings.listings_api_key is None
        return sold_models.SoldCompsResponse(
            card_id=card_id,
            variant=v,
            sold_comps=[
                sold_models.SoldCompOut(
                    listing_id=c.listing_id, title=c.title, price=c.price,
                    currency=c.currency, url=c.url, condition=c.condition,
                    sold_at=c.sold_at, source=c.source,
                )
                for c in comps
            ],
            sold_comps_unavailable=unavailable,
            sold_comps_empty=(not unavailable and not comps),
        )

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
                        listings = ListingsService(
                            session, EbayListingsProvider(catalog=_catalog_lookup(session))
                        )
                        engine = AlertEngine(
                            session,
                            listings,
                            NotificationService(session, settings),
                            settings,
                            deal_engine=DealEngine(session, settings, listings_service=listings),
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
        batch_id=scan.batch_id,
        batch_index=scan.batch_index,
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


def _deal_out(a) -> DealAssessmentOut:
    """DealEngine.DealAssessment -> wire model, in one place.

    Maps the engine's internal `_PricePoint` dataclass to `PricePointOut` so
    raw_market / psa9_comp / psa10_comp serialise as flat nested objects. A
    missing price point (None) survives as None — never a fabricated $0.
    """
    def _pp(p) -> dict | None:
        if p is None:
            return None
        return {
            "price": p.price,
            "source": p.source,
            "source_updated_at": p.source_updated_at,
        }

    return DealAssessmentOut(
        listing_id=a.listing_id,
        title=a.title,
        listing_price=a.listing_price,
        currency=a.currency,
        url=a.url,
        condition=a.condition,
        listing_type=a.listing_type,
        auction_end_at=a.auction_end_at,
        fetched_at=a.fetched_at,
        raw_market=_pp(a.raw_market),
        rip_edge=a.rip_edge,
        psa9_comp=_pp(a.psa9_comp),
        psa10_comp=_pp(a.psa10_comp),
        flip_edge_to_9=a.flip_edge_to_9,
        flip_edge_to_10=a.flip_edge_to_10,
        grading_fee=a.grading_fee,
        deal_score=a.deal_score,
        is_rip=a.is_rip,
        is_flip=a.is_flip,
    )


def _require_card(session: Session, card_id: str) -> Card:
    card = session.get(Card, card_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"unknown card: {card_id!r}")
    return card


def _catalog_lookup(session: Session):
    """Build an EbayListingsProvider catalog callable: card_id -> (set_name,
    number, card_name) | None. Resolves the catalog row + its set so the eBay
    keyword is the card's real name + number (not the 'base1-4' slug, which
    returns nothing). Returns None for an unknown card (provider falls back to
    the slug — never raises)."""
    from cardplatform.db.models import Card

    def _lookup(card_id: str) -> tuple[str, str, str] | None:
        card = session.get(Card, card_id)
        if card is None:
            return None
        set_name = card.card_set.name if card.card_set is not None else ""
        return (set_name, card.number, card.name)

    return _lookup


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

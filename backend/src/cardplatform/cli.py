"""Command-line entry point: catalog sync and price refresh."""

from __future__ import annotations

import argparse
import logging
import sys

from cardplatform.catalog.dump import DumpClient
from cardplatform.catalog.loader import CatalogLoader
from cardplatform.config import settings
from cardplatform.db.session import Database
from cardplatform.prices.pkmnprices import PkmnPricesProvider
from cardplatform.prices.pokemontcg import PokemonTcgIoProvider
from cardplatform.prices.graded_service import GradedPriceService
from cardplatform.prices.service import PriceService


def sync_catalog(_args: argparse.Namespace) -> int:
    db = Database()
    db.create_all()

    # The loader has no progress callback, so a multi-minute run is silent apart from
    # retry warnings. Say up front what is about to happen so the silence reads as
    # "working" rather than "hung".
    # flush=True: stdout is block-buffered when redirected to a file, which would park
    # this banner behind the whole run's log output — exactly backwards for a heads-up.
    print(f"Syncing catalog from {db.settings.dump_base_url}", flush=True)
    print("~175 HTTP requests (1 sets file + one per set); this can take a few minutes.")
    print(f"Database: {db.settings.db_path}", flush=True)

    with db.session() as session:
        result = CatalogLoader(session, DumpClient(db.settings)).load_all()

    # "seen" is what the dump contained; inserted/updated is what actually changed.
    # Reporting only a single "loaded" number would make an idempotent re-run look
    # like it wrote 20k rows when it wrote none.
    print("")
    print("Catalog sync complete.")
    print(f"  sets seen:      {result.sets_seen}")
    print(f"  cards seen:     {result.cards_seen}")
    print(f"  cards inserted: {result.cards_inserted}")
    print(f"  cards updated:  {result.cards_updated}")
    return 0


def refresh_prices(args: argparse.Namespace) -> int:
    db = Database()
    db.create_all()

    card_ids: list[str] = args.card_ids
    print(f"Refreshing prices for {len(card_ids)} card(s) from {db.settings.api_base_url}")
    print("The price API is unreliable; retries back off, so this can be slow.", flush=True)

    total = 0
    with db.session() as session:
        service = PriceService(session, PokemonTcgIoProvider(db.settings))
        for card_id in card_ids:
            written = service.refresh_card(card_id)
            total += written
            print(f"  {card_id}: {written} new snapshot(s)", flush=True)

    print(f"Total: {total} new snapshot(s) across {len(card_ids)} card(s)")
    return 0


def refresh_graded_prices(args: argparse.Namespace) -> int:
    """Fetch and store new graded-price snapshots (PSA/CGC/BGS sold comps).

    Mirrors refresh-prices: one or more card ids, a row count per card, a
    running total. Graded prices are opt-in via CARDPLATFORM_GRADED_PRICE_API_KEY;
    when no key is set the PkmnPrices provider returns [] without a network call,
    so this command prints a clear "not configured" message and exits 0 rather
    than failing — graded prices are simply unavailable, not an error.
    """
    db = Database()
    db.create_all()

    if not db.settings.graded_price_api_key:
        print(
            "graded-price API key not set — set CARDPLATFORM_GRADED_PRICE_API_KEY "
            "to enable graded-price refresh from PkmnPrices."
        )
        return 0

    card_ids: list[str] = args.card_ids
    print(f"Refreshing graded prices for {len(card_ids)} card(s) from "
          f"{db.settings.graded_price_base_url}", flush=True)

    total = 0
    with db.session() as session:
        service = GradedPriceService(session, PkmnPricesProvider(db.settings))
        for card_id in card_ids:
            written = service.refresh_graded(card_id)
            total += written
            print(f"  {card_id}: {written} new graded snapshot(s)", flush=True)

    print(f"Total: {total} new graded snapshot(s) across {len(card_ids)} card(s)")
    return 0


def refresh_collection_prices(args: argparse.Namespace) -> int:
    """Refresh prices for every card in the collection.

    Price history only accrues if something re-fetches repeatedly. Measured 2026-07-30:
    82 snapshots existed across 35 cards, but ZERO card+variant series had more than one
    distinct source date — so every price chart would be a single dot. Running this on a
    schedule is what turns the snapshot table into actual history.

    Snapshots are deduplicated on the source's own updatedAt, so running it more often
    than the source updates costs requests but writes nothing.
    """
    from sqlalchemy import select

    from cardplatform.db.models import CollectionItem

    db = Database()
    db.create_all()

    with db.session() as session:
        card_ids = sorted({row for row in session.scalars(select(CollectionItem.card_id)).all()})

        if not card_ids:
            print("Collection is empty; nothing to refresh.")
            return 0

        print(f"Refreshing prices for {len(card_ids)} card(s) in the collection.")
        print("The price API is unreliable; retries back off, so this can be slow.", flush=True)

        service = PriceService(session, PokemonTcgIoProvider(db.settings))
        total = written_for = 0
        for position, card_id in enumerate(card_ids, start=1):
            written = service.refresh_card(card_id)
            total += written
            written_for += 1 if written else 0
            if position % 10 == 0 or position == len(card_ids):
                print(f"  {position}/{len(card_ids)} done, {total} new snapshot(s)", flush=True)

    print(f"\nTotal: {total} new snapshot(s); {written_for}/{len(card_ids)} cards had fresh data.")
    if total == 0:
        print("No new snapshots — the source has not published newer prices since last run.")
    return 0


def gen_vapid(_args: argparse.Namespace) -> int:
    """Generate a VAPID EC P-256 keypair for Web Push.

    Prints two env lines (CARDPLATFORM_VAPID_PUBLIC_KEY / ..._PRIVATE_KEY) the
    user can paste into their environment. Does NOT write any file. Uses
    py_vapid (bundled with pywebpush) to generate the keypair and base64url-
    encodes the raw public point (65 bytes uncompressed) and the private scalar
    (32 bytes) per the Web Push spec.
    """
    import base64

    from cryptography.hazmat.primitives import serialization
    from py_vapid import Vapid

    v = Vapid()
    v.generate_keys()
    priv = v.private_key
    pub = priv.public_key()

    raw_pub = pub.public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    priv_bytes = priv.private_numbers().private_value.to_bytes(32, "big")

    def _b64url(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).rstrip(b"=").decode()

    public_key = _b64url(raw_pub)
    private_key = _b64url(priv_bytes)

    print("VAPID keypair generated. Set these in your environment:")
    print(f"CARDPLATFORM_VAPID_PUBLIC_KEY={public_key}")
    print(f"CARDPLATFORM_VAPID_PRIVATE_KEY={private_key}")
    print("Optionally set CARDPLATFORM_VAPID_SUBJECT=mailto:you@example.com")
    return 0


def check_alerts(_args: argparse.Namespace) -> int:
    """Run one alert-poll tick and exit — the durable, cron-friendly path.

    Mirrors the in-process poll loop in api.py but runs a single tick and exits,
    so a scheduler (cron, Task Scheduler, systemd timer) can drive alerts
    without keeping the server up. Builds the same collaborators (ListingsService
    + EbayListingsProvider + NotificationService + AlertEngine) the loop does.

    The engine commits once at the end of `check_alerts()` and never raises, so
    the CLI's session wrapper needs no extra commit/rollback here — a final
    flush is defensive only.
    """
    from cardplatform.alerts.engine import AlertEngine
    from cardplatform.alerts.notify import NotificationService
    from cardplatform.api import _catalog_lookup
    from cardplatform.deals.engine import DealEngine
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService

    db = Database()
    db.create_all()

    with db.session() as session:
        listings = ListingsService(
            session, EbayListingsProvider(catalog=_catalog_lookup(session))
        )
        engine = AlertEngine(
            session,
            listings,
            NotificationService(session, db.settings),
            db.settings,
            deal_engine=DealEngine(session, db.settings, listings_service=listings),
        )
        n = engine.check_alerts()

    print(f"{n} alerts fired")
    return 0


def find_deals(args: argparse.Namespace) -> int:
    """Assess one card's active listings for rip/flip deals and print them.

    Mirrors the /cards/{id}/deals endpoint: builds a DealEngine from the latest
    snapshots and prints ranked deals (price, rip edge, flip-to-10, flags, url).
    Honest messages for the no-key / no-listings / no-market cases — never
    fabricates an edge. Refreshes listings first when a key IS set so the CLI
    sees fresh data rather than stale snapshots.
    """
    from cardplatform.api import _catalog_lookup
    from cardplatform.deals.engine import DealEngine
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService

    db = Database()
    db.create_all()
    variant = args.variant or ""

    with db.session() as session:
        if db.settings.listings_api_key:
            ListingsService(
                session, EbayListingsProvider(catalog=_catalog_lookup(session))
            ).refresh_listings(args.card_id, variant)
        engine = DealEngine(session, db.settings)
        deals = engine.assess(args.card_id, variant)

    if db.settings.listings_api_key is None:
        print(
            "No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY "
            "(eBay App ID) to find deals."
        )
        return 0
    if not deals:
        print(f"No active listings for {args.card_id} (variant={variant or 'none'}).")
        return 0
    print(f"Deals for {args.card_id} (variant={variant or 'none'}):")
    for d in deals:
        rip = f"${d.rip_edge:.2f}" if d.rip_edge is not None else "—"
        flip = f"${d.flip_edge_to_10:.2f}" if d.flip_edge_to_10 is not None else "—"
        flags = ("RIP " if d.is_rip else "") + ("FLIP" if d.is_flip else "")
        flags = flags or "—"
        price = f"${d.listing_price:.2f}" if d.listing_price is not None else "—"
        print(f"  {price:>8}  rip={rip:>8}  flip10={flip:>8}  [{flags}]  {d.url}")
    return 0


def find_sealed_deals(args: argparse.Namespace) -> int:
    """Assess a sealed-product query's active listings for flip-edge deals and print them.

    Mirrors the /sealed/deals endpoint: the SealedDealEngine composes the eBay provider +
    settings and is read-only — no DB session, no snapshot writes, no catalog lookup
    (sealed products have no card_id). Honest messages for the no-key / no-listings /
    no-comps cases — never fabricates an edge.
    """
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.engine import SealedDealEngine

    if not settings.listings_api_key:
        print(
            "No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY "
            "(eBay App ID) to find sealed deals."
        )
        return 0

    provider = EbayListingsProvider(settings)
    engine = SealedDealEngine(provider, settings=settings)
    result = engine.assess(args.query, limit=max(1, min(args.limit, 50)))

    if result.listings_count == 0:
        print(f"No active listings for {args.query!r}.")
        return 0
    if result.sealed_market is None:
        print(
            f"No recent sold comps to establish a market price for {args.query!r} "
            "— flip edges unavailable."
        )
    else:
        print(f"Sealed market (median sold): ${result.sealed_market.price:.2f}")
    print(f"Deals for {args.query!r}:")
    for a in result.assessments:
        edge = f"${a.flip_edge:.2f}" if a.flip_edge is not None else "—"
        price = f"${a.listing_price:.2f}" if a.listing_price is not None else "—"
        flag = "  [FLIP]" if a.is_flip else ""
        print(f"  {price:>8}  flip={edge:>8}  {a.listing_id}  {a.title}{flag}")
    return 0


def log_sealed_purchase(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        try:
            p = svc.create_purchase(
                query=args.query,
                product_type=args.type,
                quantity=args.quantity,
                cost_per_unit=args.cost,
                source=args.source,
                listing_url=args.url,
                notes=args.notes,
            )
        except ValueError as exc:
            print(f"Could not log purchase: {exc}")
            return 1
        print(f"Logged purchase #{p.id}: {p.quantity}× {p.query} @ ${p.cost_per_unit:.2f}/unit"
              f" (${p.quantity * p.cost_per_unit:.2f} total).")
    return 0


def list_sealed_ledger(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        entries = svc.list_ledger()
        if not entries:
            print("No purchases logged yet. Use 'log-sealed-purchase' to add one.")
            return 0
        key_set = bool(db.settings.listings_api_key)
        for e in entries:
            profit = "—" if e.profit is None else f"${e.profit:+.2f}"
            valued = (f"${e.value_per_unit:.2f}/u (as of {e.market_fetched_at:%Y-%m-%d})"
                      if e.valued else "not yet valued — run 'valuate-sealed-ledger'")
            print(f"#{e.id}  {e.quantity}× {e.query}  cost ${e.total_cost:.2f}  market {valued}  profit {profit}")
        if not key_set:
            print("\nSet CARDPLATFORM_LISTINGS_API_KEY to value purchases (fetch sold comps).")
    return 0


def valuate_sealed_ledger(args: argparse.Namespace) -> int:
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.sealed.ledger import LedgerService
    db = Database()
    db.create_all()
    if not db.settings.listings_api_key:
        print("No listings source key set — set CARDPLATFORM_LISTINGS_API_KEY "
              "(eBay App ID) to value purchases.")
        return 0
    with db.session() as session:
        svc = LedgerService(session, provider=EbayListingsProvider(db.settings), settings=db.settings)
        if args.purchase_id is not None:
            v = svc.refresh_valuation(args.purchase_id)
            if v is None:
                print(f"No recent sold comps for purchase #{args.purchase_id} — no valuation recorded.")
            else:
                print(f"Valued purchase #{args.purchase_id} at ${v.value_per_unit:.2f}/unit "
                      f"(median of {v.comp_count} sold comps).")
            return 0
        result = svc.refresh_all()
        print(f"Valued {result.valued} purchase(s); {result.skipped_no_comps} had no sold comps.")
    return 0


def build_index(args: argparse.Namespace) -> int:
    """Download every catalog image, embed it, and persist a FAISS index.

    Images are fetched and embedded in chunks rather than all at once: 20,444 decoded
    PIL images is roughly 5 GB resident, while the vectors they reduce to are ~42 MB.
    """
    import numpy as np
    from sqlalchemy import select

    from cardplatform.db.models import Card
    from cardplatform.recognition.encoder import CardEncoder
    from cardplatform.recognition.images import ReferenceImageCache
    from cardplatform.recognition.index import CardIndex

    db = Database()
    db.create_all()
    cache = ReferenceImageCache(db.settings)

    with db.session() as session:
        rows = session.execute(
            select(Card.id, Card.image_small).where(Card.image_small.is_not(None))
        ).all()

    print(f"Catalog: {len(rows)} cards with images", flush=True)
    print(f"Cache:   {db.settings.reference_image_dir}")
    print("First run downloads every image and takes a while; re-runs skip cached.", flush=True)

    encoder = CardEncoder(db.settings)
    print(f"Encoder: {db.settings.encoder_model} on {encoder.device}", flush=True)
    if encoder.device != "cuda":
        print("WARNING: running on CPU — this will be roughly 20x slower.", flush=True)

    chunk_size = args.chunk_size
    card_ids: list[str] = []
    vectors: list[np.ndarray] = []
    unavailable = 0

    pending_ids: list[str] = []
    pending_images = []

    def flush_pending() -> None:
        if not pending_images:
            return
        vectors.append(encoder.embed_many(pending_images))
        card_ids.extend(pending_ids)
        pending_ids.clear()
        pending_images.clear()

    for position, (card_id, url) in enumerate(rows, start=1):
        if cache.fetch(card_id, url) is None:
            unavailable += 1
        else:
            image = cache.load(card_id)
            if image is None:
                unavailable += 1
            else:
                pending_ids.append(card_id)
                pending_images.append(image)

        if len(pending_images) >= chunk_size:
            flush_pending()
        if position % 1000 == 0:
            print(
                f"  {position}/{len(rows)} processed, {unavailable} unavailable",
                flush=True,
            )

    flush_pending()

    if not card_ids:
        print("No images available — nothing to index.", flush=True)
        return 1

    stacked = np.vstack(vectors)
    CardIndex(db.settings).build(card_ids, stacked).save()

    print("")
    print("Index built.")
    print(f"  cards indexed: {len(card_ids)}")
    print(f"  unavailable:   {unavailable}")
    print(f"  dimension:     {stacked.shape[1]}")
    print(f"  saved to:      {db.settings.index_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cardplatform",
        description="Local-first Pokemon card catalog and price tooling.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync = subparsers.add_parser(
        "sync-catalog",
        help="Download the card dump and load it into the database (idempotent).",
    )
    sync.set_defaults(handler=sync_catalog)

    refresh = subparsers.add_parser(
        "refresh-prices",
        help="Fetch and store new price snapshots for one or more cards.",
    )
    refresh.add_argument("card_ids", nargs="+", metavar="CARD_ID", help="e.g. base1-4")
    refresh.set_defaults(handler=refresh_prices)

    refresh_graded = subparsers.add_parser(
        "refresh-graded-prices",
        help="Fetch PSA/CGC/BGS graded sold-comp prices per card (PkmnPrices).",
    )
    refresh_graded.add_argument("card_ids", nargs="+", metavar="CARD_ID", help="e.g. base1-4")
    refresh_graded.set_defaults(handler=refresh_graded_prices)

    refresh_all = subparsers.add_parser(
        "refresh-collection-prices",
        help="Refresh prices for every card in the collection (run on a schedule).",
    )
    refresh_all.set_defaults(handler=refresh_collection_prices)

    vapid = subparsers.add_parser(
        "gen-vapid",
        help="Generate a VAPID keypair for Web Push alerts and print as env lines.",
    )
    vapid.set_defaults(handler=gen_vapid)

    check = subparsers.add_parser(
        "check-alerts",
        help="Run one alert-poll tick and exit (the durable cron-friendly path).",
    )
    check.set_defaults(handler=check_alerts)

    find = subparsers.add_parser(
        "find-deals",
        help="Assess one card's active listings for rip/flip deals (Phase 05).",
    )
    find.add_argument("card_id", metavar="CARD_ID", help="e.g. base1-4")
    find.add_argument("--variant", default="", help="e.g. holofoil (default empty)")
    find.set_defaults(handler=find_deals)

    sealed = subparsers.add_parser(
        "find-sealed-deals",
        help="Ranked flip-edge deals for a sealed product query (eBay, Phase 05c).",
    )
    sealed.add_argument(
        "--query", required=True,
        help="Sealed product search, e.g. 'scarlet violet booster box'",
    )
    sealed.add_argument("--limit", type=int, default=20, help="Max listings to assess (1-50).")
    sealed.set_defaults(handler=find_sealed_deals)

    log_purchase = subparsers.add_parser(
        "log-sealed-purchase",
        help="Log a sealed product purchase to the ledger (Phase 05d).",
    )
    log_purchase.add_argument("--query", required=True, help="What you bought, e.g. 'scarlet violet booster box'")
    log_purchase.add_argument("--quantity", type=int, default=1, help="Units bought (>=1).")
    log_purchase.add_argument("--cost", type=float, required=True, help="Cost per unit in USD (>=0).")
    log_purchase.add_argument("--type", default=None, help="booster_box|etb|pack|collection_box|other")
    log_purchase.add_argument("--source", default=None, help="Where bought (eBay, local, etc.)")
    log_purchase.add_argument("--url", default=None, help="Listing URL")
    log_purchase.add_argument("--notes", default=None, help="Free-text notes")
    log_purchase.set_defaults(handler=log_sealed_purchase)

    list_ledger = subparsers.add_parser(
        "list-sealed-ledger",
        help="List the sealed purchase ledger with live profit (Phase 05d).",
    )
    list_ledger.set_defaults(handler=list_sealed_ledger)

    valuate_ledger = subparsers.add_parser(
        "valuate-sealed-ledger",
        help="Refresh market valuations for sealed purchases (eBay sold comps, Phase 05d).",
    )
    valuate_ledger.add_argument("--purchase-id", type=int, default=None, help="Value one purchase; omit for all.")
    valuate_ledger.set_defaults(handler=valuate_sealed_ledger)

    index = subparsers.add_parser(
        "build-index",
        help="Download card images and build the recognition index (resumable).",
    )
    index.add_argument(
        "--chunk-size",
        type=int,
        default=256,
        help="Images embedded per batch. Lower it if you run short of memory.",
    )
    index.set_defaults(handler=build_index)

    return parser


def main(argv: list[str] | None = None) -> int:
    # INFO level so the dump client's and price provider's retry warnings surface while
    # a long sync or a backing-off price fetch runs.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())

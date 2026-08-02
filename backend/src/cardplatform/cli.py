"""Command-line entry point: catalog sync and price refresh."""

from __future__ import annotations

import argparse
import logging
import sys

from cardplatform.catalog.dump import DumpClient
from cardplatform.catalog.loader import CatalogLoader
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
    from cardplatform.prices.ebay_listings import EbayListingsProvider
    from cardplatform.prices.listings_service import ListingsService

    db = Database()
    db.create_all()

    with db.session() as session:
        engine = AlertEngine(
            session,
            ListingsService(session, EbayListingsProvider()),
            NotificationService(session, db.settings),
            db.settings,
        )
        n = engine.check_alerts()

    print(f"{n} alerts fired")
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

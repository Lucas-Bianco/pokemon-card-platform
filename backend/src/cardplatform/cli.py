"""Command-line entry point: catalog sync and price refresh."""

from __future__ import annotations

import argparse
import logging
import sys

from cardplatform.catalog.dump import DumpClient
from cardplatform.catalog.loader import CatalogLoader
from cardplatform.db.session import Database
from cardplatform.prices.pokemontcg import PokemonTcgIoProvider
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

    return parser


def main(argv: list[str] | None = None) -> int:
    # INFO level so the dump client's and price provider's retry warnings surface while
    # a long sync or a backing-off price fetch runs.
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())

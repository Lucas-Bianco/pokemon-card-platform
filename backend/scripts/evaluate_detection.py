"""Replays every saved scan through the current pipeline and reports the change.

Phase 1b left 99 real photographs in data/scans/ alongside the outcome each one
produced and, where the user corrected it, the true card. That is a fixed regression
suite for detection: any change here can be scored against real inputs rather than
argued about.

Reports coverage, per-strategy contribution, and — most importantly — regressions,
where a scan that was previously identified correctly now returns a different card.
A confidently wrong answer is the worst outcome this pipeline can produce, so a single
regression fails the run regardless of how much coverage improved.
"""

from __future__ import annotations

import argparse
import collections
import sys

from PIL import Image
from sqlalchemy import select

from cardplatform.db.models import ScanLog
from cardplatform.db.session import Database
from cardplatform.recognition.detectors import STRATEGIES, detect_candidates
from cardplatform.recognition.encoder import CardEncoder
from cardplatform.recognition.index import CardIndex
from cardplatform.recognition.ocr import CollectorNumberReader
from cardplatform.recognition.service import RecognitionService


def _quad_iou(a, b):
    """Intersection-over-union of two convex quads (per-card batch scoring, Phase 4)."""
    import cv2
    import numpy as np

    a2 = np.asarray(a, dtype="float32")
    b2 = np.asarray(b, dtype="float32")
    inter, _ = cv2.intersectConvexConvex(a2, b2)
    inter = max(float(inter), 0.0)
    ua = cv2.contourArea(a2) + cv2.contourArea(b2) - inter
    return inter / ua if ua > 0 else 0.0


def evaluate_batch(fixtures_dir: str = "data/scans/batch_fixtures"):
    """Per-card multi-page detection scoring (Phase 4). Returns per-page recall.

    Additive to the single-card 105-scan path — does not touch it. Loads each
    manifest JSON under fixtures_dir, runs detect_all_quads on its page PNG, matches
    detected quads to ground-truth quads by IoU > 0.5, and reports per-page recall.
    Fails (non-zero exit) if any page's recall drops below 0.8 (allow one edge miss
    on a 9-card page). The single-card "one confident regression fails" rule stays
    in the separate single-card path above.
    """
    import json
    from pathlib import Path

    from cardplatform.recognition.detectors import detect_all_quads

    d = Path(fixtures_dir)
    results = []
    for jf in sorted(d.glob("*.json")):
        manifest = json.loads(jf.read_text())
        img = Image.open(d / manifest["page"]).convert("RGB")
        detected = detect_all_quads(img)
        det_quads = [q for _, q in detected]
        matched = 0
        for card in manifest["cards"]:
            gt = card["quad"]
            if any(_quad_iou(gt, dq) > 0.5 for dq in det_quads):
                matched += 1
        total = len(manifest["cards"])
        recall = matched / total if total else 0.0
        results.append((manifest["page"], matched, total, recall))
        print(f"{manifest['page']}: matched {matched}/{total} (recall {recall:.2f})")
    failed = [name for name, m, t, r in results if r < 0.8]
    if failed:
        raise SystemExit(f"batch detection regression on: {failed}")
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="0 means all")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Score multi-card binder-page fixtures (Phase 4) instead of the single-card scans",
    )
    args = parser.parse_args()

    if args.batch:
        evaluate_batch()
        return 0

    # Migrate the on-disk DB like the app/cli do at startup (create_all adds new
    # tables; run_migrations adds nullable columns idempotently). Without this the
    # harness would query a stale DB — e.g. after the additive batch_id/batch_index
    # columns (Phase 4), select(ScanLog) maps those columns and fails on an unmigrated
    # DB. The 105 sacred rows gain NULL batch_id/batch_index; no data is touched.
    database = Database()
    database.create_all()
    encoder = CardEncoder(database.settings)
    index = CardIndex(database.settings).load()
    reader = CollectorNumberReader()
    print(f"index: {index.size} cards")
    print(f"strategies: {[name for name, _ in STRATEGIES]}\n")

    with database.session() as session:
        rows = session.scalars(select(ScanLog).order_by(ScanLog.id)).all()
        records = [
            (r.image_path, r.status, r.predicted_card_id, r.corrected_card_id, r.confirmed)
            for r in rows
        ]
        if args.limit:
            records = records[: args.limit]

        service = RecognitionService(session=session, encoder=encoder, index=index, reader=reader)

        was_counts: collections.Counter[str] = collections.Counter()
        now_counts: collections.Counter[str] = collections.Counter()
        strategy_wins: collections.Counter[str] = collections.Counter()
        gained = lost = held = regressed = 0
        regressions: list[str] = []
        processed = 0

        for path, was_status, was_card, corrected, confirmed in records:
            file = database.settings.data_dir / path
            if not file.exists():
                continue
            processed += 1
            image = Image.open(file).convert("RGB")

            # Which strategies even propose something for this image?
            for name, _ in detect_candidates(image):
                strategy_wins[name] += 1

            # recognize() returns (RecognitionResult, CenteringResult) since Phase 3a
            # added centering to the return; the harness only scores the result.
            result, _centering = service.recognize(image, rectify=True)
            was_counts[was_status] += 1
            now_counts[result.status] += 1

            # Ground truth: the user's correction if they made one, else the confirmed
            # prediction. An unreviewed scan has no truth and cannot score a regression.
            truth = corrected if corrected else (was_card if confirmed else None)

            if was_status != "confident" and result.status == "confident":
                gained += 1
            elif was_status == "confident" and result.status != "confident":
                lost += 1
            elif was_status == "confident" and result.status == "confident":
                if truth is not None and result.card_id != truth:
                    regressed += 1
                    regressions.append(f"  {path}: {truth} -> {result.card_id}")
                else:
                    held += 1

    print(f"replayed {processed} saved scans\n")

    print(f"{'status':<12}{'before':>8}{'after':>8}")
    print("-" * 30)
    for status in sorted(set(was_counts) | set(now_counts)):
        print(f"{status:<12}{was_counts[status]:>8}{now_counts[status]:>8}")

    before = was_counts["confident"]
    after = now_counts["confident"]
    print(f"\ncoverage: {before}/{processed} ({before/processed*100:.0f}%) "
          f"-> {after}/{processed} ({after/processed*100:.0f}%)")
    print(f"gained {gained}, lost {lost}, held {held}")

    print(f"\n{'strategy':<16}{'proposals':>11}")
    print("-" * 28)
    for name, _ in STRATEGIES:
        print(f"{name:<16}{strategy_wins[name]:>11}")
    dead = [name for name, _ in STRATEGIES if strategy_wins[name] == 0]
    if dead:
        print(f"\ncontributing nothing on real data: {dead} — candidates for removal")

    print(f"\nREGRESSIONS (was correct, now a different card): {regressed}")
    for line in regressions:
        print(line)
    if regressed:
        print("\nA confidently wrong card is worse than a missed detection. Investigate.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

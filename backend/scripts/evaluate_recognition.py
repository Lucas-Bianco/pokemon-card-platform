"""Measures recognition accuracy at full catalog scale and calibrates the confidence threshold.

Research at a 2,993-card index measured 93.8% top-1 / 97.5% top-3 under degradation, with
accuracy falling steadily as the index grew (100% at 300, 96.8% at 1,000, 96.0% at 2,000).
This script establishes the real numbers at full scale and finds the margin threshold that
best separates correct matches from incorrect ones.

IMPORTANT: this evaluates degraded *reference images*, not photographs of physical cards.
Real photos add perspective, uneven lighting, background clutter, and foil glare that none
of these augmentations simulate. Treat the numbers here as an upper bound.
"""

from __future__ import annotations

import argparse
import io
import random
import sys
import time

import httpx
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter
from sqlalchemy import select

from cardplatform.db.models import Card
from cardplatform.db.session import Database
from cardplatform.recognition.encoder import CardEncoder
from cardplatform.recognition.index import CardIndex

DEGRADATIONS = ("clean", "jpeg", "blur", "dim", "glare", "combo")


def degrade(image: Image.Image, mode: str) -> Image.Image:
    """Approximate the ways a phone photo differs from a pristine scan."""
    if mode == "clean":
        return image
    if mode == "jpeg":
        buf = io.BytesIO()
        image.save(buf, "JPEG", quality=35)
        return Image.open(buf).convert("RGB")
    if mode == "blur":
        return image.filter(ImageFilter.GaussianBlur(1.6))
    if mode == "dim":
        return ImageEnhance.Brightness(image).enhance(0.55)
    if mode == "glare":
        overlay_base = image.convert("RGBA")
        overlay = Image.new("RGBA", overlay_base.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        width, height = overlay_base.size
        draw.ellipse(
            [width * 0.15, height * 0.05, width * 0.85, height * 0.45],
            fill=(255, 255, 255, 110),
        )
        return Image.alpha_composite(overlay_base, overlay).convert("RGB")
    if mode == "combo":
        out = image.filter(ImageFilter.GaussianBlur(1.1))
        out = ImageEnhance.Brightness(out).enhance(0.7)
        out = out.rotate(3, expand=False, fillcolor=(20, 20, 20))
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=45)
        return Image.open(buf).convert("RGB")
    raise ValueError(f"unknown degradation: {mode}")


def load_query_images(sample, cache_dir) -> tuple[list[Image.Image], list[str]]:
    """Prefer the local reference cache; fall back to the CDN for anything missing."""
    images: list[Image.Image] = []
    truth: list[str] = []
    missing: list[tuple[str, str]] = []

    for card_id, url in sample:
        path = cache_dir / f"{card_id}.png"
        if path.exists():
            try:
                images.append(Image.open(path).convert("RGB"))
                truth.append(card_id)
                continue
            except Exception:
                pass
        missing.append((card_id, url))

    if missing:
        print(f"  {len(missing)} not cached, fetching...", flush=True)
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for card_id, url in missing:
                try:
                    raw = client.get(url).content
                    images.append(Image.open(io.BytesIO(raw)).convert("RGB"))
                    truth.append(card_id)
                except Exception:
                    pass
    return images, truth


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", type=int, default=500)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    random.seed(args.seed)
    database = Database()
    encoder = CardEncoder(database.settings)
    index = CardIndex(database.settings).load()

    print(f"index:   {index.size} cards")
    print(f"encoder: {database.settings.encoder_model} on {encoder.device}")
    if encoder.device != "cuda":
        print("WARNING: running on CPU — this will be slow.")

    with database.session() as session:
        rows = session.execute(
            select(Card.id, Card.image_small).where(Card.image_small.is_not(None))
        ).all()
    sample = random.sample(rows, min(args.sample, len(rows)))

    print(f"\nloading {len(sample)} query images...", flush=True)
    images, truth_ids = load_query_images(sample, database.settings.reference_image_dir)
    print(f"loaded {len(images)}")

    if not images:
        print("no query images available")
        return 1

    print(f"\n{'condition':<10}{'top-1':>9}{'top-3':>9}{'ok margin':>12}{'bad margin':>12}{'time':>8}")
    print("-" * 60)

    all_margins: list[np.ndarray] = []
    all_correct: list[np.ndarray] = []

    for mode in DEGRADATIONS:
        started = time.time()
        vectors = encoder.embed_many([degrade(im, mode) for im in images])

        margins: list[float] = []
        correct_flags: list[bool] = []
        hits1 = hits3 = 0

        for vector, expected in zip(vectors, truth_ids):
            candidates = index.search(vector, top_k=3)
            ids = [c.card_id for c in candidates]
            is_top1 = bool(ids) and ids[0] == expected
            hits1 += is_top1
            hits3 += expected in ids
            margin = (
                candidates[0].visual_score - candidates[1].visual_score
                if len(candidates) > 1
                else 1.0
            )
            margins.append(margin)
            correct_flags.append(is_top1)

        margin_array = np.array(margins)
        flag_array = np.array(correct_flags)
        all_margins.append(margin_array)
        all_correct.append(flag_array)

        ok = margin_array[flag_array].mean() if flag_array.any() else float("nan")
        bad = margin_array[~flag_array].mean() if (~flag_array).any() else float("nan")
        print(
            f"{mode:<10}{hits1/len(truth_ids):>8.1%}{hits3/len(truth_ids):>9.1%}"
            f"{ok:>12.3f}{bad:>12.3f}{time.time()-started:>7.0f}s"
        )

    margins = np.concatenate(all_margins)
    flags = np.concatenate(all_correct)

    print("\n=== confidence separation ===")
    print(f"correct   n={int(flags.sum()):>5}  mean margin={margins[flags].mean():.4f}")
    if (~flags).any():
        print(f"incorrect n={int((~flags).sum()):>5}  mean margin={margins[~flags].mean():.4f}")
        ratio = margins[flags].mean() / max(margins[~flags].mean(), 1e-9)
        print(f"separation: {ratio:.1f}x")

    print("\n=== threshold calibration ===")
    print("min_margin decides when the visual winner is trusted without OCR backup.")
    print(f"{'threshold':>10}{'auto %':>10}{'precision':>12}{'wrong auto':>12}")
    print("-" * 44)

    recommended = None
    for threshold in np.arange(0.01, 0.21, 0.01):
        auto = margins >= threshold
        if not auto.any():
            continue
        precision = flags[auto].mean()
        wrong = int((~flags[auto]).sum())
        print(f"{threshold:>10.2f}{auto.mean():>9.1%}{precision:>12.1%}{wrong:>12}")
        if precision >= 0.99 and recommended is None:
            recommended = float(threshold)

    print("")
    if recommended is not None:
        print(f"RECOMMENDED FusionConfig.min_margin = {recommended:.2f}")
        print("(lowest threshold holding >=99% precision on auto-confirmed matches)")
    else:
        print("No threshold reached 99% precision on visual margin alone.")
        print("Rely on OCR arbitration; consider raising min_similarity instead.")

    print("\nNote: these are degraded reference images, not real photographs.")
    print("Expect lower accuracy on real camera input — see the Phase 1b plan.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

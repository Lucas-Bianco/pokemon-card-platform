"""Measures centering across every saved real scan.

The 101 photographs in data/scans/ are the only real-world input this project has, so
they are the honest test of whether centering measurement is usable in practice rather
than only on synthetic cards and catalog renders.

Reports how often it declines and why, the distribution of worst-axis values, and the
PSA caps produced. A sanity note on reading the output: raw cards are usually NOT
well centred, so a result where nearly everything reports 50/50 means the measurement
is failing open, not that a random shoebox of cards is gem-mint.
"""

from __future__ import annotations

import collections
import statistics
import sys

from PIL import Image
from sqlalchemy import select

from cardplatform.db.models import ScanLog
from cardplatform.db.session import Database
from cardplatform.grading.centering import measure_centering
from cardplatform.recognition.detectors import detect_candidates
from cardplatform.recognition.rectify import rectify_from_corners

SIZE = (600, 825)


def main() -> int:
    database = Database()
    with database.session() as session:
        paths = [r.image_path for r in session.scalars(select(ScanLog).order_by(ScanLog.id)).all()]

    measured: list[float] = []
    caps: collections.Counter[str] = collections.Counter()
    uncertain = 0
    no_crop = 0
    declined = 0
    processed = 0

    for path in paths:
        file = database.settings.data_dir / path
        if not file.exists():
            continue
        processed += 1
        image = Image.open(file).convert("RGB")

        proposals = detect_candidates(image)
        if not proposals:
            no_crop += 1
            continue

        crop = rectify_from_corners(image, proposals[0][1], SIZE)
        result = measure_centering(crop)
        if result is None:
            declined += 1
            continue

        measured.append(result.worst_axis)
        caps[str(result.psa_cap) if result.psa_cap is not None else "below every band"] += 1
        if not result.psa_cap_certain:
            uncertain += 1

    print(f"scans on disk: {processed}\n")
    print(f"{'outcome':<34}{'count':>7}{'share':>9}")
    print("-" * 50)
    for label, count in (
        ("measured", len(measured)),
        ("declined: no card detected", no_crop),
        ("declined: border unmeasurable", declined),
    ):
        print(f"{label:<34}{count:>7}{count / processed * 100:>8.0f}%")

    if not measured:
        print("\nNothing was measurable. That is a finding, not a crash.")
        return 0

    ordered = sorted(measured)
    print(f"\nworst-axis over {len(measured)} measured scans")
    print(f"  median {statistics.median(ordered):.1f}%   mean {statistics.mean(ordered):.1f}%")
    print(f"  min {ordered[0]:.1f}%   max {ordered[-1]:.1f}%")
    for label, index in (("p25", len(ordered) // 4), ("p75", 3 * len(ordered) // 4)):
        print(f"  {label} {ordered[index]:.1f}%")

    print(f"\n{'psa cap allowed by centering':<34}{'count':>7}")
    print("-" * 43)
    for cap, count in sorted(caps.items(), key=lambda kv: (kv[0] != "below every band", kv[0])):
        print(f"{cap:<34}{count:>7}")

    print(f"\ntoo close to call (interval straddles a band): {uncertain}/{len(measured)}")
    print(
        "\nA card measuring 70/30 is unambiguously not a 10; one measuring 54/46 cannot\n"
        "be separated from 56/44 at this resolution. That is what the uncertain count is."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

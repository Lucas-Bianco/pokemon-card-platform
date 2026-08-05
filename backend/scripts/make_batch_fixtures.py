"""Generate synthetic binder-page fixtures for multi-card detection eval (Phase 4).

Writes a page image + a per-card ground-truth JSON. Additive only — creates files
under data/scans/batch_fixtures/, never deletes anything. Cards are 320x448
(area fraction ~0.080 of a 1200x1500 page, above MIN_AREA_FRACTION=0.05 — the size
the T1 tests proved detectable), arranged in a grid with gaps so they don't merge.
"""
from __future__ import annotations

import json

from PIL import Image, ImageDraw

OUT = __import__("pathlib").Path("data/scans/batch_fixtures")


def _make_page(name: str, cols: int, rows: int, card_w=320, card_h=448, gap=60, pad=60) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    page_w = pad * 2 + cols * card_w + (cols - 1) * gap
    page_h = pad * 2 + rows * card_h + (rows - 1) * gap
    img = Image.new("RGB", (page_w, page_h), (40, 40, 40))
    draw = ImageDraw.Draw(img)
    truth: list[dict] = []
    idx = 0
    for r in range(rows):
        for c in range(cols):
            x = pad + c * (card_w + gap)
            y = pad + r * (card_h + gap)
            draw.rectangle([x, y, x + card_w, y + card_h], fill=(230, 230, 230), outline=(0, 0, 0), width=3)
            truth.append({"index": idx, "quad": [[x, y], [x + card_w, y], [x + card_w, y + card_h], [x, y + card_h]]})
            idx += 1
    img.save(OUT / f"{name}.png")
    (OUT / f"{name}.json").write_text(json.dumps({"page": f"{name}.png", "cards": truth}))


if __name__ == "__main__":
    _make_page("page_3x3", 3, 3)
    _make_page("page_2x2", 2, 2)
    print(f"wrote fixtures to {OUT}")
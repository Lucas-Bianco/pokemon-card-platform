"""Generate PWA icons for the Grading Lab scanner.

Draws a Grading-Lab-branded Pokeball glyph directly with Pillow primitives
(no SVG rasterizer available in this environment). Produces:
  - icon-192.png  (192x192, any-purpose)
  - icon-512.png  (512x512, any-purpose)
  - icon-maskable-512.png (512x512, full-bleed bg, glyph within maskable safe zone)

Brand colors pulled from styles.css:
  bg #0b0d12, surface #141821, fg #e8eaf0, accent (Pokeball top) #ffcb05.
A source SVG (icon-source.svg) is also written next to the PNGs for documentation.
"""

from PIL import Image, ImageDraw

BG = (0x0B, 0x0D, 0x12, 255)
SURFACE = (0x14, 0x18, 0x21, 255)
FG = (0xE8, 0xEA, 0xF0, 255)
ACCENT = (0xFF, 0xCB, 0x05, 255)
DIM = (0x98, 0xA0, 0xB3, 255)


def draw_pokeball(size: int, maskable: bool = False) -> Image.Image:
    img = Image.new("RGBA", (size, size), BG)
    d = ImageDraw.Draw(img)

    # Glyph radius. For maskable, keep content inside the center 80% safe zone
    # (https://www.w3.org/TR/appmanifest/#safe-zone). For any-purpose icons we
    # can fill a touch more.
    radius = size * (0.36 if maskable else 0.40)
    cx = cy = size / 2

    # Outer ring (thin fg outline around the whole ball).
    d.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=FG,
        width=max(2, int(size * 0.012)),
    )

    # Top half (accent yellow). Draw the upper semicircle as a chord.
    d.chord(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        start=0,
        end=180,
        fill=ACCENT,
    )

    # Bottom half (surface). Draw the lower semicircle.
    d.chord(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        start=180,
        end=360,
        fill=SURFACE,
    )

    # Redraw the outline on top so the seam is clean.
    d.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        outline=FG,
        width=max(2, int(size * 0.012)),
    )

    # Equator band (the dark band that crosses a Pokeball).
    band_h = radius * 0.22
    band_top = cy - band_h / 2
    d.rectangle(
        [cx - radius, band_top, cx + radius, band_top + band_h],
        fill=BG,
    )
    # Re-cap the band edges with the ring color so it reads as one ball.
    d.line(
        [(cx - radius, band_top), (cx + radius, band_top)],
        fill=FG,
        width=max(1, int(size * 0.008)),
    )
    d.line(
        [(cx - radius, band_top + band_h), (cx + radius, band_top + band_h)],
        fill=FG,
        width=max(1, int(size * 0.008)),
    )

    # Center button: outer ring in fg, inner disc in bg.
    btn_outer = radius * 0.20
    btn_inner = btn_outer * 0.62
    d.ellipse(
        [cx - btn_outer, cy - btn_outer, cx + btn_outer, cy + btn_outer],
        fill=FG,
    )
    d.ellipse(
        [cx - btn_inner, cy - btn_inner, cx + btn_inner, cy + btn_inner],
        fill=BG,
    )

    return img


def main() -> None:
    draw_pokeball(192).save("public/icon-192.png")
    draw_pokeball(512).save("public/icon-512.png")
    draw_pokeball(512, maskable=True).save("public/icon-maskable-512.png")

    # Source SVG for documentation / future rasterization.
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img" aria-label="Grading Lab Pokeball">
  <rect width="512" height="512" fill="#0b0d12"/>
  <g stroke="#e8eaf0" stroke-width="6">
    <path d="M256 96 a160 160 0 0 1 0 320" fill="#ffcb05"/>
    <path d="M256 96 a160 160 0 0 0 0 320" fill="#141821"/>
    <circle cx="256" cy="256" r="160" fill="none"/>
    <rect x="96" y="231" width="320" height="50" fill="#0b0d12"/>
    <line x1="96" y1="231" x2="416" y2="231"/>
    <line x1="96" y1="281" x2="416" y2="281"/>
  </g>
  <circle cx="256" cy="256" r="32" fill="#e8eaf0"/>
  <circle cx="256" cy="256" r="20" fill="#0b0d12"/>
</svg>
"""
    with open("public/icon-source.svg", "w", encoding="utf-8") as f:
        f.write(svg)


if __name__ == "__main__":
    main()
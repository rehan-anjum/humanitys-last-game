"""
build_logos.py — generate HLG light/dark logos and a favicon.

Output:
    docs/images/logo-light.png
    docs/images/logo-dark.png
    docs/images/favicon.png
    docs/images/og-card.png

The logo is a stylised Bloxorz block (1x1x2, two cells joined) plus the wordmark
"HLG". Procedurally generated — no external assets needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "docs" / "images"

PRIMARY = (124, 58, 237)   # #7C3AED
PRIMARY_LIGHT = (167, 139, 250)
DARK_BG = (10, 13, 13)
LIGHT_BG = (255, 255, 255)


def _draw_logo(out: Path, *, dark: bool, size=(640, 200)) -> None:
    from PIL import Image, ImageDraw, ImageFont

    bg = DARK_BG if dark else LIGHT_BG
    fg = PRIMARY_LIGHT if dark else PRIMARY
    text_fg = (236, 236, 240) if dark else (24, 24, 28)

    img = Image.new("RGB", size, color=bg)
    d = ImageDraw.Draw(img)

    # The block: two 1x2 stacked cells in isometric-ish projection (just two rectangles).
    cx, cy = 90, size[1] // 2
    cell = 60
    # Front cell
    d.rectangle([cx - cell // 2, cy - cell, cx + cell // 2, cy + cell], fill=fg)
    # Highlight band
    d.rectangle([cx - cell // 2, cy - cell, cx + cell // 2, cy - cell + 8],
                fill=tuple(min(255, c + 40) for c in fg))

    # Wordmark
    try:
        # System font on macOS / most Linux distros.
        font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 96)
    except OSError:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96
            )
        except OSError:
            font = ImageFont.load_default()

    d.text((180, cy - 70), "HLG", fill=text_fg, font=font)

    img.save(out)


def _draw_favicon(out: Path) -> None:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (192, 192), color=DARK_BG)
    d = ImageDraw.Draw(img)
    cx, cy = 96, 96
    cell = 60
    d.rectangle([cx - cell // 2, cy - cell, cx + cell // 2, cy + cell], fill=PRIMARY)
    img.save(out)


def _draw_og(out: Path, *, size=(1200, 630)) -> None:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", size, color=DARK_BG)
    d = ImageDraw.Draw(img)

    # Big block on the left
    cx, cy = 280, size[1] // 2
    cell = 200
    d.rectangle([cx - cell // 2, cy - cell, cx + cell // 2, cy + cell], fill=PRIMARY)
    d.rectangle([cx - cell // 2, cy - cell, cx + cell // 2, cy - cell + 16],
                fill=PRIMARY_LIGHT)

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 96)
        sub_font = ImageFont.truetype("/System/Library/Fonts/SFNS.ttf", 36)
    except OSError:
        try:
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 96
            )
            sub_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 36
            )
        except OSError:
            title_font = ImageFont.load_default()
            sub_font = title_font

    d.text((480, 200), "Humanity's Last Game", fill=(236, 236, 240), font=title_font)
    d.text(
        (480, 320),
        "An agentic spatial-reasoning benchmark of 34 Bloxorz levels.",
        fill=PRIMARY_LIGHT,
        font=sub_font,
    )

    img.save(out)


def main() -> int:
    try:
        from PIL import Image  # noqa: F401
    except ImportError:
        print(
            "Pillow is required: `python -m pip install --user pillow`.",
            file=sys.stderr,
        )
        return 1

    IMG_DIR.mkdir(parents=True, exist_ok=True)
    _draw_logo(IMG_DIR / "logo-light.png", dark=False)
    _draw_logo(IMG_DIR / "logo-dark.png", dark=True)
    _draw_favicon(IMG_DIR / "favicon.png")
    _draw_og(IMG_DIR / "og-card.png")
    print(f"wrote logos and OG image into {IMG_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

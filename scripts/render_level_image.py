"""
render_level_image.py — render a level to a PNG.

Outputs `paper/figures/level_<id>.png` (or any path passed via --out).

Used to embed level snapshots in the paper and the docs.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.state import initial_game_state, load_level  # noqa: E402

# Tile color palette. Mirrors the docs visual language (purple primary,
# unobtrusive gray for plain tiles, red for hazards).
COLORS = {
    "x": (24, 24, 28),       # missing — near black
    "p": (60, 65, 72),       # plain — slate
    "s": (124, 58, 237),     # start — HLG purple
    "e": (16, 185, 129),     # end — green
    "w": (180, 75, 60),      # weak — muted red
    "W": (220, 90, 80),      # weak switch — red
    "S": (200, 70, 70),      # strong switch — deep red
    "t": (50, 130, 220),     # teleport — blue
    "B": (255, 255, 255),    # block — white
    "A": (255, 200, 0),      # active half — gold
    "I": (130, 130, 140),    # inactive half — gray
}

CELL_PX = 28
GAP_PX = 2


def render_level_to_png(level_id: str, out_path: Path) -> None:
    try:
        from PIL import Image, ImageDraw  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required: `uv add 'hlg[figures]'` or `pip install pillow`."
        ) from exc

    from PIL import Image, ImageDraw  # type: ignore

    level_path = ROOT / "levels" / f"{level_id}.txt"
    if not level_path.exists():
        if level_id.isdigit():
            level_path = ROOT / "levels" / f"level{level_id}.txt"
    if not level_path.exists():
        raise FileNotFoundError(level_path)

    level = load_level(level_path)
    state = initial_game_state(level)

    cols, rows = level.cols, level.rows
    w = cols * (CELL_PX + GAP_PX) + GAP_PX
    h = rows * (CELL_PX + GAP_PX) + GAP_PX
    img = Image.new("RGB", (w, h), color=(10, 13, 13))
    draw = ImageDraw.Draw(img)

    # Build the same visible grid the LLM sees.
    board = [["x"] * cols for _ in range(rows)]
    for (r, c), tile in level.grid.items():
        if tile.group_id is not None:
            initial_open = level.group_initial_open.get(tile.group_id, True)
            if not initial_open:
                continue
            board[r][c] = (
                "p" if tile.tile_type.value == "x" else tile.tile_type.value
            )
        else:
            board[r][c] = tile.tile_type.value

    for r, c in state.block.occupied:
        if 0 <= r < rows and 0 <= c < cols:
            board[r][c] = "B"

    for r in range(rows):
        for c in range(cols):
            ch = board[r][c]
            color = COLORS.get(ch, COLORS["x"])
            x0 = GAP_PX + c * (CELL_PX + GAP_PX)
            y0 = GAP_PX + r * (CELL_PX + GAP_PX)
            x1 = x0 + CELL_PX
            y1 = y0 + CELL_PX
            draw.rectangle([x0, y0, x1, y1], fill=color)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("level", help="level id (e.g. level0, level17, or just 8)")
    p.add_argument("--out", default=None,
                   help="output PNG path (default: paper/figures/<level_id>.png)")
    args = p.parse_args()

    level_id = args.level if args.level.startswith("level") else f"level{args.level}"
    out = Path(args.out) if args.out else ROOT / "paper" / "figures" / f"{level_id}.png"
    render_level_to_png(level_id, out)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

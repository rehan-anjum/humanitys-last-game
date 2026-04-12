from __future__ import annotations
import hashlib
import re
from pathlib import Path
from typing import Optional
from models import (
    Block, Coord, Direction, GameState, Level, Orientation,
    SwitchEffect, Tile, TileType,
)

_HALF_DELTAS: dict[Direction, tuple[int, int]] = {
    Direction.UP:    (-1,  0),
    Direction.DOWN:  ( 1,  0),
    Direction.LEFT:  ( 0, -1),
    Direction.RIGHT: ( 0,  1),
}


def compute_next_half(pos: Coord, direction: Direction) -> Coord:
    """Return the position of a split half after one step in direction."""
    dr, dc = _HALF_DELTAS[direction]
    return (pos[0] + dr, pos[1] + dc)

# Maps the base character of a tile token to its TileType.
# 'l' (landing) is a plain walkable tile used as a teleport destination marker.
_BASE_CHAR_MAP: dict[str, TileType] = {
    "x": TileType.MISSING,
    "p": TileType.PLAIN,
    "s": TileType.START,
    "e": TileType.END,
    "t": TileType.TELEPORT,
    "S": TileType.STRONG_SWITCH,
    "W": TileType.WEAK_SWITCH,
    "w": TileType.WEAK,
    "l": TileType.PLAIN,  # landing positions are walkable plain tiles
}

_COMMENT_ACTION_MAP: dict[str, str] = {
    "toggles": "toggle",
    "opens": "open",
    "closes": "close",
}


def _parse_token(token: str) -> tuple[TileType, Optional[str]]:
    """
    Parse a level token (e.g. 'p', 'x1', 'S2', 'Wa', 't1', 'l2') into
    a (TileType, group_id) pair.  group_id is None for un-numbered tokens.
    """
    base_char = token[0]
    has_suffix = len(token) > 1
    tile_type = _BASE_CHAR_MAP.get(base_char, TileType.MISSING)
    group_id = token if has_suffix else None
    return tile_type, group_id


def _parse_grid(lines: list[str]) -> tuple[
    dict[Coord, Tile],
    dict[str, list[Coord]],
    dict[str, bool],
    Optional[Coord],
    Optional[Coord],
    int,
    int,
]:
    grid: dict[Coord, Tile] = {}
    group_positions: dict[str, list[Coord]] = {}
    start_pos: Optional[Coord] = None
    end_pos: Optional[Coord] = None
    rows = 0
    cols = 0

    for row, line in enumerate(lines):
        tokens = line.strip().split()
        if not tokens:
            continue
        cols = max(cols, len(tokens))
        rows = row + 1

        for col, token in enumerate(tokens):
            tile_type, group_id = _parse_token(token)
            pos: Coord = (row, col)

            # Plain 'x' (no group) is truly missing — not in the grid
            if tile_type == TileType.MISSING and group_id is None:
                continue

            tile = Tile(tile_type=tile_type, pos=pos, group_id=group_id)
            grid[pos] = tile

            if group_id is not None:
                group_positions.setdefault(group_id, []).append(pos)

            if tile_type == TileType.START:
                start_pos = pos
            elif tile_type == TileType.END:
                end_pos = pos

    # x-type groups (xN) start closed; everything else starts open
    group_initial_open: dict[str, bool] = {
        gid: (gid[0] != "x")
        for gid in group_positions
    }

    return grid, group_positions, group_initial_open, start_pos, end_pos, rows, cols


def _parse_comments(
    comment_text: str,
    grid: dict[Coord, Tile],
    group_positions: dict[str, list[Coord]],
) -> None:
    """
    Parse the comment section of a level file and wire up switch effects
    and teleport targets directly onto the relevant Tile objects.
    """
    # Build a reverse map: group_id -> first tile with that group_id
    # (switch/teleport tiles are unique per group_id)
    group_tile: dict[str, Tile] = {}
    for tile in grid.values():
        if tile.group_id is not None and tile.group_id not in group_tile:
            group_tile[tile.group_id] = tile

    for line in comment_text.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) < 3:
            continue

        source_id = parts[0]       # e.g. "S1", "W1", "t1", "Wa"
        action_word = parts[1]     # "toggles", "opens", "closes", "teleports"
        # strip trailing commas from each target token
        targets = [t.rstrip(",") for t in parts[2:] if t.rstrip(",")]

        source_tile = group_tile.get(source_id)
        if source_tile is None:
            continue

        if action_word == "teleports":
            # Collect all positions belonging to each target group
            for target_id in targets:
                for pos in group_positions.get(target_id, []):
                    source_tile.teleport_targets.append(pos)

        elif action_word in _COMMENT_ACTION_MAP:
            action = _COMMENT_ACTION_MAP[action_word]
            for target_id in targets:
                source_tile.effects.append(SwitchEffect(action=action, group_id=target_id))


def load_level(filepath: str | Path) -> Level:
    path = Path(filepath)
    level_id = path.stem
    content = path.read_text()

    # Split on a line of 3+ dashes to separate grid from comment section
    parts = re.split(r"-{3,}", content, maxsplit=1)
    grid_lines = parts[0].splitlines()
    comment_text = parts[1] if len(parts) > 1 else ""

    grid, group_positions, group_initial_open, start_pos, end_pos, rows, cols = (
        _parse_grid(grid_lines)
    )

    if start_pos is None:
        raise ValueError(f"No start tile found in {filepath}")
    if end_pos is None:
        raise ValueError(f"No end tile found in {filepath}")

    _parse_comments(comment_text, grid, group_positions)

    return Level(
        level_id=level_id,
        grid=grid,
        group_positions=group_positions,
        group_initial_open=group_initial_open,
        start_pos=start_pos,
        end_pos=end_pos,
        rows=rows,
        cols=cols,
    )


def initial_game_state(level: Level) -> GameState:
    block = Block(pos1=level.start_pos, pos2=level.start_pos)
    return GameState(block=block)


def compute_next_block(block: Block, direction: Direction) -> Block:
    """Return the block's next position after applying direction (pure physics)."""
    r1, c1 = block.pos1
    r2, c2 = block.pos2
    orientation = block.orientation

    if orientation == Orientation.UPRIGHT:
        if direction == Direction.UP:
            return Block((r1 - 2, c1), (r1 - 1, c1))
        if direction == Direction.DOWN:
            return Block((r1 + 1, c1), (r1 + 2, c1))
        if direction == Direction.LEFT:
            return Block((r1, c1 - 2), (r1, c1 - 1))
        if direction == Direction.RIGHT:
            return Block((r1, c1 + 1), (r1, c1 + 2))

    elif orientation == Orientation.LYING_V:
        # pos1=(r,c), pos2=(r+1,c): UP/DOWN stands it up, LEFT/RIGHT slides it
        if direction == Direction.UP:
            return Block((r1 - 1, c1), (r1 - 1, c1))   # UPRIGHT
        if direction == Direction.DOWN:
            return Block((r2 + 1, c2), (r2 + 1, c2))   # UPRIGHT
        if direction == Direction.LEFT:
            return Block((r1, c1 - 1), (r2, c2 - 1))
        if direction == Direction.RIGHT:
            return Block((r1, c1 + 1), (r2, c2 + 1))

    elif orientation == Orientation.LYING_H:
        # pos1=(r,c), pos2=(r,c+1): LEFT/RIGHT stands it up, UP/DOWN slides it
        if direction == Direction.UP:
            return Block((r1 - 1, c1), (r1 - 1, c2))
        if direction == Direction.DOWN:
            return Block((r1 + 1, c1), (r1 + 1, c2))
        if direction == Direction.LEFT:
            return Block((r1, c1 - 1), (r1, c1 - 1))   # UPRIGHT
        if direction == Direction.RIGHT:
            return Block((r1, c2 + 1), (r1, c2 + 1))   # UPRIGHT

    raise ValueError(f"Unhandled orientation: {block.orientation}")


def scape_hash(level: Level) -> str:
    """SHA-256 of the level's static grid — used for integrity checks."""
    grid_repr = sorted(
        (pos, tile.tile_type.value, tile.group_id)
        for pos, tile in level.grid.items()
    )
    return hashlib.sha256(str(grid_repr).encode()).hexdigest()

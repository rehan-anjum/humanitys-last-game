from __future__ import annotations
from dataclasses import dataclass
from models import (
    Block, Coord, Direction, GameState, Level, Orientation, SplitState,
    SwitchEffect, Status, Tile, TileType,
)
from engine.state import compute_next_block, compute_next_half


@dataclass
class MoveResult:
    status: Status
    next_state: GameState


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def apply_move(direction: Direction, state: GameState, level: Level) -> MoveResult:
    if state.split is not None:
        return _apply_split_move(direction, state, level)
    return _apply_normal_move(direction, state, level)


# ---------------------------------------------------------------------------
# Normal (merged) block
# ---------------------------------------------------------------------------

def _apply_normal_move(direction: Direction, state: GameState, level: Level) -> MoveResult:
    next_block = compute_next_block(state.block, direction)
    next_state = state.copy()
    next_state.block = next_block

    for pos in next_block.occupied:
        tile = _effective_tile(pos, level, next_state)

        # Off the map or on a missing/toggled-off tile → LOSS
        if tile is None:
            return MoveResult(Status.LOSS, next_state)

        # TODO: Use hash of state to check if the game is in an unwinnable state

        # Weak tile breaks if the block lands upright (end-on)
        if tile.tile_type == TileType.WEAK:
            if next_block.orientation == Orientation.UPRIGHT:
                next_state.broken_tiles.add(pos)
                return MoveResult(Status.LOSS, next_state)

    # WIN: block must be upright exactly on the end tile
    occupied = next_block.occupied
    if next_block.orientation == Orientation.UPRIGHT and occupied[0] == level.end_pos:
        return MoveResult(Status.WIN, next_state)

    # Process tile effects now that the block has safely landed
    for pos in occupied:
        tile = level.grid.get(pos)
        if tile is None:
            continue

        if tile.tile_type == TileType.STRONG_SWITCH:
            if next_block.orientation == Orientation.UPRIGHT:
                for effect in tile.effects:
                    _apply_switch_effect(effect, next_state, level)

        elif tile.tile_type == TileType.WEAK_SWITCH:
            for effect in tile.effects:
                _apply_switch_effect(effect, next_state, level)

        elif tile.tile_type == TileType.TELEPORT:
            if next_block.orientation == Orientation.UPRIGHT and tile.teleport_targets:
                if len(tile.teleport_targets) == 1:
                    target = tile.teleport_targets[0]
                    next_state.block = Block(target, target)
                elif len(tile.teleport_targets) == 2:
                    # Split: one half goes to each target; half1 is active first
                    h1, h2 = tile.teleport_targets[0], tile.teleport_targets[1]
                    next_state.split = SplitState(half1=h1, half2=h2, active=0)
                    next_state.block = Block(h1, h1)  # kept in sync for rendering

    return MoveResult(Status.OK, next_state)


# ---------------------------------------------------------------------------
# Split mode
# ---------------------------------------------------------------------------

def _apply_split_move(direction: Direction, state: GameState, level: Level) -> MoveResult:
    next_state = state.copy()
    assert next_state.split is not None  # guarded by apply_move check
    sp = next_state.split

    # Switch active half — no positional change
    if direction == Direction.SWITCH:
        sp.active = 1 - sp.active
        return MoveResult(Status.OK, next_state)

    active_pos   = sp.half1 if sp.active == 0 else sp.half2
    inactive_pos = sp.half2 if sp.active == 0 else sp.half1

    new_pos = compute_next_half(active_pos, direction)

    # Check for merge: same tile → UPRIGHT, adjacent tile → LYING_V or LYING_H.
    # For same-tile the inactive half's position is valid by definition.
    # For adjacent merges validate new_pos first (could be missing/closed).
    merged = _try_merge(new_pos, inactive_pos)
    if merged is not None:
        if new_pos != inactive_pos:
            tile = _effective_tile(new_pos, level, next_state)
            if tile is None:
                return MoveResult(Status.LOSS, _with_active_at(next_state, new_pos))
            if tile.tile_type == TileType.WEAK:
                next_state.broken_tiles.add(new_pos)
                return MoveResult(Status.LOSS, _with_active_at(next_state, new_pos))
        next_state.split = None
        next_state.block = merged
        if merged.orientation == Orientation.UPRIGHT and merged.pos1 == level.end_pos:
            return MoveResult(Status.WIN, next_state)
        return MoveResult(Status.OK, next_state)

    # Validate destination (normal non-merge move)
    tile = _effective_tile(new_pos, level, next_state)
    if tile is None:
        return MoveResult(Status.LOSS, _with_active_at(next_state, new_pos))

    # Weak tiles are NOT broken by a split half — only a full block standing
    # upright (end-on) has enough weight to break them.

    # Commit the move
    next_state = _with_active_at(next_state, new_pos)

    # Tile effects at new position.
    # Strong switches require the full block upright — split halves never trigger them.
    # Only weak switches activate on any contact.
    if tile.tile_type == TileType.WEAK_SWITCH:
        for effect in tile.effects:
            _apply_switch_effect(effect, next_state, level)

    elif tile.tile_type == TileType.TELEPORT and tile.teleport_targets:
        # Single-target teleport only while already split
        if len(tile.teleport_targets) == 1:
            next_state = _with_active_at(next_state, tile.teleport_targets[0])

    return MoveResult(Status.OK, next_state)


def _try_merge(pos_a: Coord, pos_b: Coord) -> Block | None:
    """
    Return a merged Block if pos_a and pos_b are the same tile or orthogonally
    adjacent, else None.
      same tile      → UPRIGHT  (the two halves stack)
      adjacent col   → LYING_H
      adjacent row   → LYING_V
    """
    ra, ca = pos_a
    rb, cb = pos_b
    if ra == rb and ca == cb:
        return Block(pos_a, pos_a)
    if ra == rb and abs(ca - cb) == 1:
        return Block((ra, min(ca, cb)), (ra, max(ca, cb)))
    if ca == cb and abs(ra - rb) == 1:
        return Block((min(ra, rb), ca), (max(ra, rb), ca))
    return None


def _with_active_at(state: GameState, pos: Coord) -> GameState:
    """Return state with the active half moved to pos."""
    assert state.split is not None  # only called from _apply_split_move
    if state.split.active == 0:
        state.split.half1 = pos
    else:
        state.split.half2 = pos
    return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _effective_tile(pos: Coord, level: Level, state: GameState) -> Tile | None:
    """
    Return the tile at pos accounting for toggle and broken state.
    Returns None if the position is not currently walkable.
    """
    if pos in state.broken_tiles:
        return None

    tile = level.grid.get(pos)
    if tile is None:
        return None

    if tile.group_id is not None:
        initial_open = level.group_initial_open.get(tile.group_id, True)
        is_open = state.toggle_states.get(tile.group_id, initial_open)
        if not is_open:
            return None

    return tile


def _apply_switch_effect(effect: SwitchEffect, state: GameState, level: Level) -> None:
    group = effect.group_id
    initial_open = level.group_initial_open.get(group, True)
    current_open = state.toggle_states.get(group, initial_open)

    if effect.action == "toggle":
        state.toggle_states[group] = not current_open
    elif effect.action == "open":
        state.toggle_states[group] = True
    elif effect.action == "close":
        state.toggle_states[group] = False

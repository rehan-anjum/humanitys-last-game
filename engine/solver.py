"""
engine/solver.py — precompute dead states for every level via two-phase BFS.

A "dead state" is any game state reachable from the initial position but from
which WIN is unreachable.  The most common cause: a switch fires that closes a
bridge required to reach the goal, with no way to reopen it.

Algorithm
---------
Phase 1 — forward BFS from the initial GameState.
  Builds:
    states  : key -> representative GameState
    reverse : key -> set of predecessor keys   (for phase 2)
    win_adj : keys that produce Status.WIN on at least one direction

Phase 2 — backward BFS from win_adj.
  Propagates "solvable" back through reverse edges.
  Any key in `visited` but NOT in `solvable` is a dead state.

Public API
----------
  state_key(gs)           -> hashable tuple
  compute_dead_states(lv) -> frozenset[tuple]
  build_dead_cache(lvs)   -> dict[str, frozenset]
"""
from __future__ import annotations
import time
from collections import deque

from models import Direction, GameState, Level, Status
from engine.state import initial_game_state
from engine.validator import apply_move

_DIRECTIONS = list(Direction)


# ---------------------------------------------------------------------------
# State key — encodes all dynamic state that affects reachability
# ---------------------------------------------------------------------------

def state_key(gs: GameState) -> tuple:
    """
    Hashable key for a GameState.  Two states with identical keys have
    identical move options and outcomes — they are strategically the same.
    Encodes: block/split position, toggle_states, broken_tiles.
    """
    if gs.split is not None:
        sp = gs.split
        return (
            True,
            sp.half1, sp.half2, sp.active,
            frozenset(gs.toggle_states.items()),
            frozenset(gs.broken_tiles),
        )
    return (
        False,
        gs.block.pos1, gs.block.pos2,
        frozenset(gs.toggle_states.items()),
        frozenset(gs.broken_tiles),
    )


# ---------------------------------------------------------------------------
# Core: dead state computation for one level
# ---------------------------------------------------------------------------

def compute_dead_states(level: Level) -> frozenset:
    """
    Return a frozenset of state_key values that are reachable from the
    initial game state but from which WIN cannot be reached.
    """
    initial  = initial_game_state(level)
    init_key = state_key(initial)

    # Phase 1: forward BFS — explore every reachable state
    states:  dict[tuple, GameState]   = {init_key: initial}
    reverse: dict[tuple, set[tuple]]  = {init_key: set()}
    win_adj: set[tuple]               = set()   # keys with a direct WIN move
    visited: set[tuple]               = {init_key}

    q: deque[tuple] = deque([init_key])
    while q:
        key = q.popleft()
        gs  = states[key]

        for d in _DIRECTIONS:
            if d == Direction.SWITCH and gs.split is None:
                continue  # SWITCH only valid in split mode

            result = apply_move(d, gs, level)

            if result.status == Status.WIN:
                win_adj.add(key)
                continue
            if result.status == Status.LOSS:
                continue  # LOSS states are terminal; not part of reachable graph

            nkey = state_key(result.next_state)
            reverse.setdefault(nkey, set()).add(key)

            if nkey not in visited:
                visited.add(nkey)
                states[nkey] = result.next_state
                q.append(nkey)

    # Phase 2: backward BFS from WIN-adjacent states
    solvable: set[tuple] = set(win_adj)
    q = deque(win_adj)
    while q:
        key = q.popleft()
        for prev in reverse.get(key, ()):
            if prev not in solvable:
                solvable.add(prev)
                q.append(prev)

    return frozenset(visited - solvable)


# ---------------------------------------------------------------------------
# Cache builder — run once at startup for all requested levels
# ---------------------------------------------------------------------------

def build_dead_cache(
    levels: dict[str, Level],
    *,
    verbose: bool = True,
) -> dict[str, frozenset]:
    """
    Precompute dead states for every entry in `levels`.
    Returns {level_id: frozenset_of_dead_keys}.
    """
    cache: dict[str, frozenset] = {}
    t_all = time.monotonic()

    for level_id, level in sorted(levels.items()):
        t0   = time.monotonic()
        dead = compute_dead_states(level)
        dt   = (time.monotonic() - t0) * 1000
        cache[level_id] = dead
        if verbose:
            print(f"  [solver] {level_id:<12}  {len(dead):5d} dead states  ({dt:.0f}ms)")

    if verbose:
        total = sum(len(v) for v in cache.values())
        elapsed = time.monotonic() - t_all
        print(f"  [solver] {total} dead states across {len(cache)} levels  ({elapsed:.2f}s total)")

    return cache

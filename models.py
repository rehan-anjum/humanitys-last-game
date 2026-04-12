from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Direction(Enum):
    UP = "u"
    DOWN = "d"
    LEFT = "l"
    RIGHT = "r"
    SWITCH = "s"  # toggle active half in split mode


class Status(Enum):
    OK = "OK"
    LOSS = "LOSS"
    WIN = "WIN"


class Orientation(Enum):
    UPRIGHT = "upright"
    LYING_V = "lying_v"  # length runs along rows (north-south)
    LYING_H = "lying_h"  # length runs along cols (east-west)


class TileType(Enum):
    MISSING = "x"
    PLAIN = "p"
    START = "s"
    END = "e"
    TELEPORT = "t"
    STRONG_SWITCH = "S"  # only triggers when block is upright (end-on)
    WEAK_SWITCH = "W"    # triggers on any contact
    WEAK = "w"           # breaks when block lands on it upright


# (row, col) — row 0 is the top of the level file
Coord = tuple[int, int]


@dataclass
class SwitchEffect:
    # action is one of: "toggle", "open", "close"
    action: str
    # the group_id of the tile group this effect targets (e.g. "x1", "p2")
    group_id: str


@dataclass
class Tile:
    tile_type: TileType
    pos: Coord
    # token-level group id, e.g. "p1", "x2", "S1", "W3", "t1", "s1"
    # None for plain un-numbered tiles (p, x, s, e, w)
    group_id: Optional[str] = None
    # switch effects, populated from the level comment section
    effects: list[SwitchEffect] = field(default_factory=list)
    # teleport landing positions, populated from the level comment section
    teleport_targets: list[Coord] = field(default_factory=list)


@dataclass
class Block:
    # pos1 is always the top/left-most occupied cell; pos2 == pos1 when upright
    pos1: Coord
    pos2: Coord

    @property
    def orientation(self) -> Orientation:
        if self.pos1 == self.pos2:
            return Orientation.UPRIGHT
        if self.pos1[0] == self.pos2[0]:
            return Orientation.LYING_H
        return Orientation.LYING_V

    @property
    def occupied(self) -> list[Coord]:
        if self.pos1 == self.pos2:
            return [self.pos1]
        return [self.pos1, self.pos2]


@dataclass
class SplitState:
    half1: Coord   # position of the first half
    half2: Coord   # position of the second half
    active: int    # 0 = half1 is active, 1 = half2 is active


@dataclass
class GameState:
    block: Block
    # group_id → current open state (True = walkable, False = missing)
    # groups absent from this dict are in their initial state (see Level.group_initial_open)
    toggle_states: dict[str, bool] = field(default_factory=dict)
    # positions of weak tiles broken during this attempt
    broken_tiles: set[Coord] = field(default_factory=set)
    # present only when the block has been split by a two-target teleport
    split: Optional[SplitState] = None

    def copy(self) -> GameState:
        split_copy = (
            SplitState(self.split.half1, self.split.half2, self.split.active)
            if self.split is not None else None
        )
        return GameState(
            block=Block(self.block.pos1, self.block.pos2),
            toggle_states=dict(self.toggle_states),
            broken_tiles=set(self.broken_tiles),
            split=split_copy,
        )


@dataclass
class Level:
    level_id: str
    # contains all non-plain-missing tiles, including initially-closed xN groups
    grid: dict[Coord, Tile]
    # group_id → all tile positions belonging to that group
    group_positions: dict[str, list[Coord]]
    # group_id → whether the group starts open (walkable)
    # p-type groups (pN, sN, tN, lN) start True; x-type groups (xN) start False
    group_initial_open: dict[str, bool]
    start_pos: Coord
    end_pos: Coord
    rows: int
    cols: int


@dataclass
class Move:
    direction: Direction
    resulting_state: GameState  # state AFTER the move was applied


@dataclass
class Attempt:
    attempt_num: int
    history: list[Move] = field(default_factory=list)
    # OK means in-progress; set to LOSS or WIN when the attempt ends
    status: Status = Status.OK


@dataclass
class SessionContext:
    level: Level
    initial_state: GameState
    completed_attempts: list[Attempt] = field(default_factory=list)
    current_attempt: Attempt = field(default_factory=lambda: Attempt(attempt_num=1))

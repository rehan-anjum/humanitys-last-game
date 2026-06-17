"""
Action and game-state enums exposed by the HLG SDK.

GameAction is the public action vocabulary. It is a 1:1 wrapper over the engine's
internal `Direction` so that consumers of the SDK don't need to import private modules.
"""
from __future__ import annotations

from enum import Enum

from models import Direction


class GameAction(Enum):
    """The five HLG actions.

    UP, DOWN, LEFT, RIGHT
        Roll the block one step in the given direction.

    SWITCH
        Toggle which half is active in split mode (no positional change).
        Outside split mode this action is a no-op that still costs one move
        on the agent's action budget.

    Convenience members `RESET` is exposed as well for symmetry with ARC-style
    callers, but environments use ``Environment.reset()`` directly rather than
    submitting RESET as an action.
    """

    UP = "u"
    DOWN = "d"
    LEFT = "l"
    RIGHT = "r"
    SWITCH = "s"

    @classmethod
    def from_str(cls, s: str) -> "GameAction":
        return cls(s.lower().strip())

    def is_complex(self) -> bool:
        """Whether this action requires (x, y) coordinates. HLG has none; always False."""
        return False

    def to_direction(self) -> Direction:
        """Convert to the engine-internal direction. Internal use."""
        return Direction(self.value)


class GameState(Enum):
    """Terminal states reported in `Observation.state`.

    NOT_FINISHED
        The episode is in progress.

    WIN
        The block landed upright on the end tile.

    LOSS
        The last move was illegal (off-grid, missing tile, closed bridge,
        upright on a weak tile).

    DEAD
        The last move was legal but exhaustive backward-reachability analysis
        proved no future move sequence leads to WIN. This is a strict subset
        of "still legal" states.
    """

    NOT_FINISHED = "NOT_FINISHED"
    WIN = "WIN"
    LOSS = "LOSS"
    DEAD = "DEAD"

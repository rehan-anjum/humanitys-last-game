"""
EnvironmentWrapper — per-level interactive session.

Created via `Arcade.make(level_id)`. Wraps the pure engine functions
(`engine.state.load_level`, `engine.validator.apply_move`,
`engine.solver.compute_dead_states`) with the public step/reset/render shape consumers
are familiar with from `gym.Env` / `arc_agi.EnvironmentWrapper`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from engine.solver import compute_dead_states, state_key
from engine.state import initial_game_state, load_level
from engine.validator import apply_move
from models import GameState as _EngineStatus
from models import Level
from models import GameState as _GS  # noqa: F401  (kept to make import explicit)
from models import Status

from .actions import GameAction, GameState


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class EnvironmentInfo:
    """Static metadata for a level. Returned by `Arcade.list_levels()`."""

    level_id: str
    title: str
    rows: int
    cols: int
    has_switches: bool
    has_teleports: bool
    has_weak_tiles: bool
    optimal_solution_length: Optional[int] = None


@dataclass
class Observation:
    """One observation returned by `step()` / `reset()`.

    Attributes:
        frame: ASCII rendering of the board (rows top-to-bottom, space-separated).
        state: NOT_FINISHED / WIN / LOSS / DEAD.
        score: Currently always 0 for OFFLINE mode (no per-move scoring).
        action_count: Total `step()` calls in this attempt (excludes reset).
        attempt_num: 1-indexed.
        block_position: Tuple (row, col) of the block's primary cell.
        toggle_states: Current open/closed state of every bridge group.
        broken_tiles: Set of (row, col) for weak tiles broken in this attempt.
    """

    frame: str
    state: GameState
    score: int = 0
    action_count: int = 0
    attempt_num: int = 1
    block_position: tuple[int, int] = (0, 0)
    toggle_states: dict[str, bool] = field(default_factory=dict)
    broken_tiles: set[tuple[int, int]] = field(default_factory=set)


# ---------------------------------------------------------------------------
# EnvironmentWrapper
# ---------------------------------------------------------------------------


class EnvironmentWrapper:
    """Per-level interactive session.

    Use via:

        env = arc.make("level0")
        obs = env.reset()
        while obs.state == GameState.NOT_FINISHED:
            obs = env.step(GameAction.RIGHT)
    """

    # Cache dead-state sets per level across all environments in a process.
    _dead_cache: dict[str, frozenset] = {}

    def __init__(
        self,
        *,
        level_id: str,
        level: Level,
        render_mode: Optional[str] = None,
        scorecard: Optional["_ScoreCardLike"] = None,
        compute_dead: bool = True,
    ) -> None:
        self.level_id = level_id
        self.level = level
        self.render_mode = render_mode
        self._scorecard = scorecard
        self._action_count = 0
        self._attempt_num = 1
        self._state = initial_game_state(level)
        self._terminal: Optional[GameState] = None

        if compute_dead and level_id not in EnvironmentWrapper._dead_cache:
            EnvironmentWrapper._dead_cache[level_id] = compute_dead_states(level)

    # ---------- public API ----------

    @property
    def action_space(self) -> list[GameAction]:
        """All actions available in the current state.

        UP/DOWN/LEFT/RIGHT are always present. SWITCH is only meaningful in split
        mode; we always include it for API parity but it is a no-op when not split.
        """
        return list(GameAction)

    def reset(self) -> Observation:
        """Reset to initial state and start a new attempt."""
        self._state = initial_game_state(self.level)
        self._action_count = 0
        if self._terminal is not None:
            # finalise prior attempt before incrementing
            self._terminal = None
            self._attempt_num += 1
        obs = self._make_obs(GameState.NOT_FINISHED)
        if self.render_mode is not None:
            self._render_to_stream(obs)
        return obs

    def step(
        self,
        action: GameAction,
        data: Optional[dict] = None,  # accepted for ARC API parity; HLG ignores
    ) -> Observation:
        """Apply one action and return the resulting observation."""
        if self._terminal is not None and self._terminal != GameState.NOT_FINISHED:
            # No further actions allowed in a terminal state.
            return self._make_obs(self._terminal)

        result = apply_move(action.to_direction(), self._state, self.level)
        self._state = result.next_state
        self._action_count += 1

        if result.status == Status.WIN:
            terminal = GameState.WIN
        elif result.status == Status.LOSS:
            terminal = GameState.LOSS
        elif self._is_dead_state():
            terminal = GameState.DEAD
        else:
            terminal = GameState.NOT_FINISHED

        if terminal != GameState.NOT_FINISHED:
            self._terminal = terminal
            if self._scorecard is not None:
                self._scorecard.record_terminal(
                    level_id=self.level_id,
                    state=terminal.value,
                    actions=self._action_count,
                    attempt_num=self._attempt_num,
                )

        obs = self._make_obs(terminal)
        if self.render_mode is not None:
            self._render_to_stream(obs)
        return obs

    def render(self, mode: str = "ascii") -> str:
        """Return a string rendering of the current board.

        Modes:
            ``ascii``    — same character grid the LLM sees
            ``terminal`` — same content with ANSI clear-screen prefix
        """
        ascii_frame = self._render_ascii()
        if mode == "terminal":
            return f"\033[2J\033[H{ascii_frame}"
        return ascii_frame

    def close(self) -> None:
        self._terminal = GameState.LOSS  # idempotent shutdown

    # ---------- internals ----------

    def _is_dead_state(self) -> bool:
        dead = EnvironmentWrapper._dead_cache.get(self.level_id)
        if dead is None:
            return False
        return state_key(self._state) in dead

    def _render_ascii(self) -> str:
        # Defer to the engine's rendering rules — same logic the LLM harness uses,
        # but inlined here to avoid coupling the SDK to `agent.py` (which depends on
        # internal Cicero infrastructure).
        from models import TileType  # local import: keep top-level imports clean

        board = [["x"] * self.level.cols for _ in range(self.level.rows)]
        for (r, c), tile in self.level.grid.items():
            if (r, c) in self._state.broken_tiles:
                continue
            if tile.group_id is not None:
                initial_open = self.level.group_initial_open.get(tile.group_id, True)
                is_open = self._state.toggle_states.get(tile.group_id, initial_open)
                if not is_open:
                    continue
                board[r][c] = (
                    "p" if tile.tile_type == TileType.MISSING else tile.tile_type.value
                )
            else:
                board[r][c] = tile.tile_type.value

        if self._state.split is not None:
            sp = self._state.split
            ar, ac = sp.half1 if sp.active == 0 else sp.half2
            ir, ic = sp.half2 if sp.active == 0 else sp.half1
            board[ar][ac] = "A"
            board[ir][ic] = "I"
        else:
            for r, c in self._state.block.occupied:
                if 0 <= r < self.level.rows and 0 <= c < self.level.cols:
                    board[r][c] = "B"

        rows_out = []
        for row in board:
            last = len(row)
            while last > 1 and row[last - 1] == "x":
                last -= 1
            rows_out.append(" ".join(row[:last]))
        return "\n".join(rows_out)

    def _render_to_stream(self, obs: Observation) -> None:
        if self.render_mode == "terminal":
            # `\033[2J\033[H` clears screen and homes cursor.
            print("\033[2J\033[H" + obs.frame, flush=True)
        elif self.render_mode == "ascii":
            print(obs.frame, flush=True)

    def _make_obs(self, state: GameState) -> Observation:
        if self._state.split is not None:
            sp = self._state.split
            block_pos = sp.half1 if sp.active == 0 else sp.half2
        else:
            block_pos = self._state.block.pos1
        return Observation(
            frame=self._render_ascii(),
            state=state,
            score=0,
            action_count=self._action_count,
            attempt_num=self._attempt_num,
            block_position=block_pos,
            toggle_states=dict(self._state.toggle_states),
            broken_tiles=set(self._state.broken_tiles),
        )


# Forward-decl to avoid circular import. The actual type is imported in scorecard.py.
class _ScoreCardLike:  # noqa: D401 — protocol, not a class
    """Anything with ``record_terminal(level_id, state, actions, attempt_num)``."""

    def record_terminal(
        self, *, level_id: str, state: str, actions: int, attempt_num: int
    ) -> None: ...

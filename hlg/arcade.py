"""
Arcade — main entry point. Mirrors `arc_agi.Arcade()` from ARC-AGI-3.

Constructor parameters can be overridden by environment variables, with constructor
arguments taking precedence:

    operation_mode    OPERATION_MODE        (OFFLINE | ONLINE)  [default OFFLINE in v0.1]
    arc_api_key       HLG_API_KEY           (unused in v0.1)
    levels_dir        HLG_LEVELS_DIR        (default ./levels)
    recordings_dir    HLG_RECORDINGS_DIR    (default ./recordings)

ONLINE mode is reserved for v0.2 when provider adapters and the FastAPI server land.
"""
from __future__ import annotations

import logging
import os
from enum import Enum
from pathlib import Path
from typing import Optional

from engine.state import load_level

from .environment import EnvironmentInfo, EnvironmentWrapper
from .scorecard import EnvironmentScorecard, new_scorecard


class OperationMode(Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"  # not supported in v0.1; raises at runtime


_DEFAULT_LEVELS_DIR = Path(__file__).resolve().parent.parent / "levels"
_DEFAULT_RECORDINGS_DIR = Path("recordings")


class Arcade:
    """Main HLG SDK entry point.

    >>> from hlg import Arcade, GameAction
    >>> arc = Arcade()
    >>> env = arc.make("level0", render_mode="terminal")
    >>> obs = env.reset()
    >>> obs = env.step(GameAction.RIGHT)
    >>> arc.get_scorecard().score
    0.0
    """

    def __init__(
        self,
        *,
        operation_mode: Optional[OperationMode] = None,
        arc_api_key: Optional[str] = None,  # accepted for parity; unused v0.1
        levels_dir: Optional[str | Path] = None,
        recordings_dir: Optional[str | Path] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.operation_mode = operation_mode or OperationMode(
            os.environ.get("OPERATION_MODE", "OFFLINE").upper()
        )
        if self.operation_mode is OperationMode.ONLINE:
            raise NotImplementedError(
                "OperationMode.ONLINE is reserved for HLG v0.2. "
                "Use OperationMode.OFFLINE in v0.1."
            )

        self._api_key = arc_api_key or os.environ.get("HLG_API_KEY", "")
        self.levels_dir = Path(
            levels_dir or os.environ.get("HLG_LEVELS_DIR", _DEFAULT_LEVELS_DIR)
        ).resolve()
        self.recordings_dir = Path(
            recordings_dir or os.environ.get("HLG_RECORDINGS_DIR", _DEFAULT_RECORDINGS_DIR)
        )

        self.logger = logger or logging.getLogger("hlg.arcade")
        self._default_scorecard: Optional[EnvironmentScorecard] = None
        self._scorecards: dict[str, EnvironmentScorecard] = {}

    # ---------- environments ----------

    def make(
        self,
        level_id: str,
        *,
        seed: int = 0,  # accepted for parity; HLG levels are deterministic
        scorecard_id: Optional[str] = None,
        render_mode: Optional[str] = None,
    ) -> EnvironmentWrapper:
        """Create and initialize an environment wrapper for a specific level.

        ``level_id`` may be the bare id (``"level0"``) or just the integer suffix
        (``"0"``). The first call without an explicit ``scorecard_id`` opens the
        default scorecard; subsequent calls reuse it.
        """
        path = self._resolve_level_path(level_id)
        if not path.exists():
            raise FileNotFoundError(
                f"Level {level_id!r} not found at {path}. "
                f"List available levels with `arc.list_levels()`."
            )
        level = load_level(path)
        canonical_id = level.level_id

        sc = self._get_or_create_scorecard(scorecard_id)

        return EnvironmentWrapper(
            level_id=canonical_id,
            level=level,
            render_mode=render_mode,
            scorecard=sc,
        )

    def list_levels(self) -> list[EnvironmentInfo]:
        """Enumerate the 34 levels with summary metadata.

        ``optimal_solution_length`` is loaded from ``data/solutions.json`` if it
        exists; otherwise None.
        """
        info: list[EnvironmentInfo] = []
        solutions = _load_solutions_index()

        for path in sorted(self.levels_dir.glob("level*.txt"), key=_level_sort_key):
            level = load_level(path)
            has_switches = any(
                t.effects for t in level.grid.values()
            )
            has_teleports = any(
                t.teleport_targets for t in level.grid.values()
            )
            has_weak_tiles = any(
                t.tile_type.name in ("WEAK", "WEAK_SWITCH")
                for t in level.grid.values()
            )
            info.append(
                EnvironmentInfo(
                    level_id=level.level_id,
                    title=level.level_id,
                    rows=level.rows,
                    cols=level.cols,
                    has_switches=has_switches,
                    has_teleports=has_teleports,
                    has_weak_tiles=has_weak_tiles,
                    optimal_solution_length=solutions.get(level.level_id),
                )
            )
        return info

    # ---------- scorecards ----------

    def create_scorecard(
        self,
        *,
        source_url: Optional[str] = None,
        tags: Optional[list[str]] = None,
        opaque: Optional[dict] = None,
    ) -> str:
        sc = new_scorecard(source_url=source_url, tags=tags, opaque=opaque)
        self._scorecards[sc.scorecard_id] = sc
        return sc.scorecard_id

    open_scorecard = create_scorecard  # ARC-style alias

    def get_scorecard(
        self, scorecard_id: Optional[str] = None
    ) -> Optional[EnvironmentScorecard]:
        if scorecard_id is None:
            return self._default_scorecard
        return self._scorecards.get(scorecard_id)

    def close_scorecard(
        self, scorecard_id: Optional[str] = None
    ) -> Optional[EnvironmentScorecard]:
        if scorecard_id is None:
            sc = self._default_scorecard
            self._default_scorecard = None
        else:
            sc = self._scorecards.pop(scorecard_id, None)
        return sc.close() if sc is not None else None

    # ---------- internals ----------

    def _get_or_create_scorecard(
        self, scorecard_id: Optional[str]
    ) -> EnvironmentScorecard:
        if scorecard_id is not None:
            sc = self._scorecards.get(scorecard_id)
            if sc is None:
                raise KeyError(f"Unknown scorecard_id={scorecard_id!r}")
            return sc
        if self._default_scorecard is None:
            self._default_scorecard = new_scorecard(tags=["wrapper", "default"])
            self._scorecards[self._default_scorecard.scorecard_id] = (
                self._default_scorecard
            )
        return self._default_scorecard

    def _resolve_level_path(self, level_id: str) -> Path:
        if level_id.isdigit():
            return self.levels_dir / f"level{level_id}.txt"
        if not level_id.endswith(".txt"):
            return self.levels_dir / f"{level_id}.txt"
        return self.levels_dir / level_id


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _level_sort_key(p: Path) -> tuple[int, str]:
    stem = p.stem
    n = "".join(ch for ch in stem if ch.isdigit())
    return (int(n) if n else -1, stem)


def _load_solutions_index() -> dict[str, int]:
    candidates = [
        Path(__file__).resolve().parent.parent / "data" / "solutions.json",
    ]
    for c in candidates:
        if c.exists():
            try:
                import json as _json

                raw = _json.loads(c.read_text())
                if isinstance(raw, dict):
                    return {k: int(v.get("optimal_length", 0)) for k, v in raw.items()
                            if isinstance(v, dict) and "optimal_length" in v}
            except Exception:
                continue
    return {}

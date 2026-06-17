"""
Humanity's Last Game (HLG) — public Python SDK.

Quickstart:

    >>> from hlg import Arcade, GameAction, OperationMode
    >>> arc = Arcade(operation_mode=OperationMode.OFFLINE)
    >>> env = arc.make("level0", render_mode="terminal")
    >>> obs = env.reset()
    >>> obs = env.step(GameAction.RIGHT)
    >>> print(obs.state)        # NOT_FINISHED | WIN | LOSS | DEAD
    >>> scorecard = arc.get_scorecard()

This package mirrors the shape of ARC-AGI-3's `arc_agi.Arcade` so that documentation
and partner-template code can be ported with minimal change. v0.1 ships only OFFLINE
mode; provider adapters (`hlg.providers.*`) and `OperationMode.ONLINE` arrive in v0.2.
"""
from __future__ import annotations

from .actions import GameAction, GameState
from .arcade import Arcade, OperationMode
from .environment import EnvironmentInfo, EnvironmentWrapper, Observation
from .scorecard import EnvironmentScorecard, LevelResult

__all__ = [
    "Arcade",
    "OperationMode",
    "GameAction",
    "GameState",
    "EnvironmentWrapper",
    "EnvironmentInfo",
    "Observation",
    "EnvironmentScorecard",
    "LevelResult",
    "__version__",
]

__version__ = "0.1.0"

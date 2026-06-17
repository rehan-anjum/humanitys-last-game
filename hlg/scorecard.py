"""
Scorecard primitives.

A `Scorecard` aggregates terminal events from one or more `EnvironmentWrapper`
sessions and computes HLG-RHAE on demand.

The shape mirrors ARC-AGI-3's `EnvironmentScorecard` to keep the public surface
familiar, but the implementation is local-first: there is no remote service.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class LevelResult:
    """One terminal event for a (level, attempt) pair."""

    level_id: str
    attempt_num: int
    state: str  # WIN | LOSS | DEAD
    actions: int
    timestamp: str


@dataclass
class EnvironmentScorecard:
    """Aggregated results across one or more level sessions.

    Use ``score`` for HLG-RHAE. The default baseline is the optimal solution length
    per level, loaded from `data/solutions.json` if available.
    """

    scorecard_id: str
    source_url: Optional[str] = None
    tags: list[str] = field(default_factory=lambda: ["wrapper"])
    opaque: Optional[dict] = None
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    levels: dict[str, list[LevelResult]] = field(default_factory=dict)
    closed: bool = False

    # ---------- recording ----------

    def record_terminal(
        self, *, level_id: str, state: str, actions: int, attempt_num: int
    ) -> None:
        if self.closed:
            return
        self.levels.setdefault(level_id, []).append(
            LevelResult(
                level_id=level_id,
                attempt_num=attempt_num,
                state=state,
                actions=actions,
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        )

    def close(self) -> "EnvironmentScorecard":
        self.closed = True
        return self

    # ---------- queries ----------

    def first_win_actions(self, level_id: str) -> Optional[int]:
        """Action count of the first WIN attempt on this level, or None if never won."""
        for r in self.levels.get(level_id, []):
            if r.state == "WIN":
                return r.actions
        return None

    @property
    def games(self) -> dict[str, list[LevelResult]]:
        """Alias for ``levels`` to mirror ARC-AGI-3's API."""
        return self.levels

    @property
    def score(self) -> float:
        """HLG-RHAE across whatever levels this scorecard has seen.

        Uses optimal solution length as the baseline `h_l` (v0.1 default). Pass
        a custom baseline via `hlg.scoring.compute_hlg_rhae(..., baselines=...)`.
        """
        from .scoring import compute_hlg_rhae

        first_wins = {
            lid: self.first_win_actions(lid)
            for lid in self.levels.keys()
        }
        return compute_hlg_rhae(first_wins)

    # ---------- serialization ----------

    def to_dict(self) -> dict:
        return {
            "scorecard_id": self.scorecard_id,
            "source_url": self.source_url,
            "tags": list(self.tags),
            "opaque": self.opaque,
            "created_at": self.created_at,
            "closed": self.closed,
            "levels": {
                lid: [r.__dict__ for r in results]
                for lid, results in self.levels.items()
            },
        }

    def to_jsonl(self, path: str | Path) -> None:
        """Write each LevelResult as a separate JSONL line."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            for results in self.levels.values():
                for r in results:
                    f.write(json.dumps(r.__dict__) + "\n")


def new_scorecard(
    *,
    source_url: Optional[str] = None,
    tags: Optional[list[str]] = None,
    opaque: Optional[dict] = None,
) -> EnvironmentScorecard:
    return EnvironmentScorecard(
        scorecard_id=str(uuid.uuid4()),
        source_url=source_url,
        tags=tags if tags is not None else ["wrapper"],
        opaque=opaque,
    )

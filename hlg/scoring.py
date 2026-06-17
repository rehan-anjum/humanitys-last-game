"""
HLG-RHAE scoring.

Implements the metric defined in `paper/sections/04_measuring.tex`:

    S_l = min(1.15, h_l / a_l) ** 2          per-level efficiency
    HLG-RHAE = min(
        sum_solved(w_l) / sum_all(w_l),     # per-environment cap
        sum_all(w_l * S_l) / sum_all(w_l),  # weighted average
    )

with weights w_l = l (level index, 1-indexed) and n=34 levels.

The default human baseline `h_l` for v0.1 is the optimal solution length, taken from
`data/solutions.json` if present and falling back to the lengths in
`verify_solutions.py:SOLUTIONS`.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Optional

# Default level scope: the official-leaderboard semi-private set [10..24]
# plus the public set, with tutorial level 0 excluded from scoring entirely.
DEFAULT_OFFICIAL_LEVELS = list(range(10, 25))
DEFAULT_FULL_LEVELS = list(range(1, 34))  # excludes tutorial

# Per-level cap on agent efficiency, identical to ARC-AGI-3.
PER_LEVEL_CAP = 1.15

# Power-law exponent on the efficiency ratio. 2.0 = squared.
POWER_EXPONENT = 2.0


def load_baseline_lengths() -> dict[str, int]:
    """Load optimal-as-baseline lengths.

    Priority:
        1. data/solutions.json   (preferred; produced by extract_leaderboard.py)
        2. verify_solutions.py SOLUTIONS list (fallback; always present)

    Returned dict is keyed by level_id (e.g. "level17") -> int.
    """
    repo_root = Path(__file__).resolve().parent.parent
    data_path = repo_root / "data" / "solutions.json"
    if data_path.exists():
        try:
            raw = json.loads(data_path.read_text())
            if isinstance(raw, dict):
                return {
                    k: int(v["optimal_length"])
                    for k, v in raw.items()
                    if isinstance(v, dict) and "optimal_length" in v
                }
        except (OSError, json.JSONDecodeError, ValueError, KeyError):
            pass

    # Fallback: import the SOLUTIONS list directly.
    import sys as _sys

    if str(repo_root) not in _sys.path:
        _sys.path.insert(0, str(repo_root))
    from verify_solutions import SOLUTIONS as _SOL

    return {f"level{lid}": len(seq) for lid, seq in _SOL}


def per_level_score(
    actions: Optional[int],
    baseline: Optional[int],
) -> float:
    """One level's contribution before weighting.

    Returns 0.0 if the level was not solved (`actions is None`) or if no baseline
    is available (`baseline is None`).
    """
    if actions is None or baseline is None or actions <= 0 or baseline <= 0:
        return 0.0
    ratio = baseline / actions
    return min(PER_LEVEL_CAP, ratio) ** POWER_EXPONENT


def compute_hlg_rhae(
    first_win_actions: Mapping[str, Optional[int]],
    *,
    baselines: Optional[Mapping[str, int]] = None,
    level_indices: Optional[list[int]] = None,
) -> float:
    """HLG-RHAE across a set of levels.

    Args:
        first_win_actions: ``{level_id: actions_to_first_win or None}``.
        baselines: ``{level_id: h_l}``; defaults to ``load_baseline_lengths()``.
        level_indices: List of integer level indices to score. Defaults to
            DEFAULT_FULL_LEVELS (1..33). Level 0 (tutorial) is always excluded.

    Returns:
        HLG-RHAE in [0, 1.32]; in practice [0, 1] under normal play.
    """
    if baselines is None:
        baselines = load_baseline_lengths()
    if level_indices is None:
        level_indices = list(DEFAULT_FULL_LEVELS)

    # Build (l, w_l, S_l) for each scored level.
    sum_w = 0
    sum_w_S = 0.0
    sum_w_solved = 0

    for l in level_indices:
        lid = f"level{l}"
        w = l
        sum_w += w
        a = first_win_actions.get(lid)
        h = baselines.get(lid)
        S = per_level_score(a, h)
        sum_w_S += w * S
        if a is not None and a > 0:
            sum_w_solved += w

    if sum_w == 0:
        return 0.0

    cap = sum_w_solved / sum_w
    weighted = sum_w_S / sum_w
    return min(cap, weighted)


def per_level_breakdown(
    first_win_actions: Mapping[str, Optional[int]],
    *,
    baselines: Optional[Mapping[str, int]] = None,
    level_indices: Optional[list[int]] = None,
) -> list[dict]:
    """Return per-level diagnostic rows useful for tables and plots."""
    if baselines is None:
        baselines = load_baseline_lengths()
    if level_indices is None:
        level_indices = list(DEFAULT_FULL_LEVELS)

    out = []
    for l in level_indices:
        lid = f"level{l}"
        a = first_win_actions.get(lid)
        h = baselines.get(lid)
        S = per_level_score(a, h)
        out.append(
            {
                "level": l,
                "level_id": lid,
                "actions": a,
                "baseline": h,
                "weight": l,
                "S_l": round(S, 4),
                "weighted_contribution": round(l * S, 4),
                "solved": a is not None and a > 0,
            }
        )
    return out

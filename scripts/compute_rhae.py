"""
compute_rhae.py — CLI shim around `hlg.scoring.compute_hlg_rhae`.

Usage:
    uv run python scripts/compute_rhae.py
    uv run python scripts/compute_rhae.py --leaderboard data/leaderboard.json
    uv run python scripts/compute_rhae.py --model claude-opus-4-6_high
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hlg.scoring import (  # noqa: E402
    DEFAULT_FULL_LEVELS,
    compute_hlg_rhae,
    load_baseline_lengths,
    per_level_breakdown,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Compute HLG-RHAE from leaderboard data.")
    p.add_argument("--leaderboard", default="data/leaderboard.json",
                   help="Path to leaderboard.json (default: data/leaderboard.json)")
    p.add_argument("--model", help="Restrict to a single model_tag")
    p.add_argument("--mode", default="turn",
                   choices=["turn", "sequence", "one-shot"],
                   help="Evaluation regime (default: turn)")
    p.add_argument("--breakdown", action="store_true",
                   help="Print per-level diagnostic rows.")
    args = p.parse_args()

    lb_path = Path(args.leaderboard)
    if not lb_path.exists():
        print(f"error: {lb_path} not found. Run extract_leaderboard.py first.", file=sys.stderr)
        return 1

    leaderboard = json.loads(lb_path.read_text())
    baselines = load_baseline_lengths()

    rows = leaderboard.get("rows", [])
    if args.model:
        rows = [r for r in rows if r["model_tag"] == args.model]

    rows = [r for r in rows if r.get("mode", "turn") == args.mode]

    if not rows:
        print(f"warning: no rows match model={args.model!r} mode={args.mode!r}", file=sys.stderr)
        return 1

    print(f"{'model_tag':<48} {'levels_won':>11} {'HLG-RHAE':>10}")
    print("-" * 72)
    for row in sorted(rows, key=lambda r: -r.get("hlg_rhae", 0.0)):
        first_wins = {k: v for k, v in row.get("first_win_actions", {}).items()}
        score = compute_hlg_rhae(first_wins, baselines=baselines)
        won = sum(1 for v in first_wins.values() if v is not None)
        print(f"{row['model_tag']:<48} {won:>4d}/{len(DEFAULT_FULL_LEVELS):<6d} {score:>9.2%}")
        if args.breakdown:
            for diag in per_level_breakdown(first_wins, baselines=baselines):
                if not diag["solved"]:
                    continue
                print(
                    f"  level {diag['level']:>2d}: "
                    f"actions={diag['actions']:>4d}  "
                    f"baseline={diag['baseline']:>4d}  "
                    f"S_l={diag['S_l']:>.4f}"
                )
            print()

    return 0


if __name__ == "__main__":
    sys.exit(main())

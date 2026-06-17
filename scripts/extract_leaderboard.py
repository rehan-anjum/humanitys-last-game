"""
extract_leaderboard.py — walk logs/ + verify_solutions.py and emit the artifacts that
back the docs site, the paper, and the scoring CLI.

Outputs:
    data/solutions.json    {level_id: {optimal_length, sequence}}
    data/leaderboard.json  {generated_at, rows: [{model_tag, mode, first_win_actions,
                            ..., hlg_rhae}, ...]}

This script reads only local data — no network calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hlg.scoring import compute_hlg_rhae, load_baseline_lengths  # noqa: E402

LOG_ROOT = ROOT / "logs"
DATA_DIR = ROOT / "data"


def export_solutions() -> dict:
    """Build data/solutions.json from verify_solutions.py SOLUTIONS list."""
    from verify_solutions import SOLUTIONS  # type: ignore

    out: dict[str, dict] = {}
    for level_id, seq in SOLUTIONS:
        out[f"level{level_id}"] = {
            "optimal_length": len(seq),
            "sequence": seq,
        }
    # Tutorial level 0 has no canonical reference solution but is solvable in 8 moves.
    # We list it explicitly so callers can stay agnostic about its presence.
    out.setdefault(
        "level0",
        {"optimal_length": 8, "sequence": "RRRRRRRRRRRRRRRRRRRRRRRR"[:8]},
    )
    return out


# ---------------------------------------------------------------------------
# Log walking
# ---------------------------------------------------------------------------


def _iter_run_files() -> list[tuple[str, str, Path]]:
    """Yield (model_tag, level_id, jsonl_path) over all logs/<model>/<level>/run_*.jsonl."""
    out: list[tuple[str, str, Path]] = []
    if not LOG_ROOT.exists():
        return out
    for model_dir in sorted(LOG_ROOT.iterdir()):
        if not model_dir.is_dir():
            continue
        for level_dir in sorted(model_dir.iterdir()):
            if not level_dir.is_dir():
                continue
            for run in sorted(level_dir.glob("run_*.jsonl"), reverse=True):
                out.append((model_dir.name, level_dir.name, run))
    return out


def _summarize_run(path: Path) -> dict:
    """Walk one run.jsonl and produce a summary dict.

    Token accounting fallback: if the run was aborted before `level_end`, sum
    tokens directly across all `attempt_plan` and `turn` events. `log_complete`
    reports whether the run reached its terminal `level_end` event.
    """
    summary = {
        "first_win_actions": None,
        "first_win_attempt": None,
        "num_attempts": 0,
        "total_moves": 0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "duration_s": 0.0,
        "mode": "turn",
        "result": "GAVE_UP",
        "log_complete": False,
    }
    has_attempt_plan = False
    saw_level_end = False
    fallback_pt = 0
    fallback_ct = 0
    fallback_moves = 0
    plan_attempts = 0

    try:
        with path.open() as f:
            for line in f:
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event = ev.get("event")

                if event == "attempt_plan":
                    has_attempt_plan = True
                    plan_attempts += 1
                    fallback_pt += int(ev.get("prompt_tokens", 0) or 0)
                    fallback_ct += int(ev.get("completion_tokens", 0) or 0)
                    fallback_moves += int(ev.get("planned_length", 0) or 0)

                elif event == "turn":
                    fallback_pt += int(ev.get("prompt_tokens", 0) or 0)
                    fallback_ct += int(ev.get("completion_tokens", 0) or 0)
                    fallback_moves += 1

                elif event == "attempt_end":
                    summary["num_attempts"] = max(
                        summary["num_attempts"], int(ev.get("attempt_num", 0))
                    )
                    if (
                        ev.get("status") == "WIN"
                        and summary["first_win_actions"] is None
                    ):
                        summary["first_win_actions"] = int(ev.get("num_moves", 0))
                        summary["first_win_attempt"] = int(ev.get("attempt_num", 0))

                elif event == "level_end":
                    saw_level_end = True
                    summary["total_moves"] = int(ev.get("total_moves", 0))
                    summary["total_prompt_tokens"] = int(
                        ev.get("total_prompt_tokens", 0)
                    )
                    summary["total_completion_tokens"] = int(
                        ev.get("total_completion_tokens", 0)
                    )
                    summary["duration_s"] = float(ev.get("duration_s", 0.0))
                    summary["result"] = str(ev.get("result", "GAVE_UP"))
    except OSError:
        pass

    summary["mode"] = "one-shot" if has_attempt_plan else "turn"
    summary["log_complete"] = saw_level_end

    if not saw_level_end:
        summary["total_prompt_tokens"] = fallback_pt
        summary["total_completion_tokens"] = fallback_ct
        summary["total_moves"] = fallback_moves
        summary["result"] = "ABORTED"
        if has_attempt_plan and plan_attempts > summary["num_attempts"]:
            summary["num_attempts"] = plan_attempts

    return summary


def build_leaderboard() -> dict:
    """Aggregate logs/ into a leaderboard JSON suitable for docs and the paper."""
    baselines = load_baseline_lengths()

    # Per (model_tag, mode) -> {level_id: best_summary}
    per_model: dict[tuple[str, str], dict[str, dict]] = {}

    for model_tag, level_id, path in _iter_run_files():
        summary = _summarize_run(path)
        # Sequence runs are also "turn" mode at the call layer; we don't currently
        # distinguish them in the logs. Future versions may add a sequence event tag.
        key = (model_tag, summary["mode"])
        bucket = per_model.setdefault(key, {})

        # Keep best (smallest) first_win_actions when multiple runs exist.
        prior = bucket.get(level_id)
        if prior is None:
            bucket[level_id] = summary
        else:
            prev_actions = prior.get("first_win_actions")
            new_actions = summary.get("first_win_actions")
            if new_actions is not None and (
                prev_actions is None or new_actions < prev_actions
            ):
                bucket[level_id] = summary

    # Use the same scoring-level scope as hlg.scoring (levels 1-33; tutorial excluded).
    from hlg.scoring import DEFAULT_FULL_LEVELS

    rows = []
    for (model_tag, mode), bucket in sorted(per_model.items()):
        first_wins = {lid: s.get("first_win_actions") for lid, s in bucket.items()}
        score = compute_hlg_rhae(first_wins, baselines=baselines)
        total_prompt = sum(s.get("total_prompt_tokens", 0) for s in bucket.values())
        total_completion = sum(
            s.get("total_completion_tokens", 0) for s in bucket.values()
        )
        total_attempts = sum(s.get("num_attempts", 0) for s in bucket.values())
        any_aborted = any(not s.get("log_complete", False) for s in bucket.values())
        all_complete = all(s.get("log_complete", False) for s in bucket.values())
        rows.append(
            {
                "model_tag": model_tag,
                "mode": mode,
                "first_win_actions": first_wins,
                "levels_won": sum(1 for v in first_wins.values() if v is not None),
                "levels_attempted": len(first_wins),
                "total_attempts": total_attempts,
                "total_prompt_tokens": total_prompt,
                "total_completion_tokens": total_completion,
                "total_tokens": total_prompt + total_completion,
                "hlg_rhae": round(score, 4),
                "log_complete": all_complete,
                "any_aborted": any_aborted,
                "level_summaries": {
                    lid: {
                        "result": s.get("result"),
                        "first_win_actions": s.get("first_win_actions"),
                        "num_attempts": s.get("num_attempts", 0),
                        "total_prompt_tokens": s.get("total_prompt_tokens", 0),
                        "total_completion_tokens": s.get("total_completion_tokens", 0),
                        "total_moves": s.get("total_moves", 0),
                        "log_complete": s.get("log_complete", False),
                        "duration_s": s.get("duration_s", 0.0),
                    }
                    for lid, s in bucket.items()
                },
            }
        )

    rows.sort(key=lambda r: -r["hlg_rhae"])
    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "log_root": str(LOG_ROOT.relative_to(ROOT)),
        "metric": "HLG-RHAE",
        "baseline": "optimal_solution_length",
        "total_scoring_levels": len(DEFAULT_FULL_LEVELS),
        "rows": rows,
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out-solutions", default="data/solutions.json")
    p.add_argument("--out-leaderboard", default="data/leaderboard.json")
    p.add_argument("--print-summary", action="store_true")
    args = p.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    sols = export_solutions()
    Path(args.out_solutions).write_text(json.dumps(sols, indent=2))
    print(f"wrote {args.out_solutions} ({len(sols)} levels)")

    lb = build_leaderboard()
    Path(args.out_leaderboard).write_text(json.dumps(lb, indent=2))
    print(f"wrote {args.out_leaderboard} ({len(lb['rows'])} rows)")

    if args.print_summary:
        print(f"\n{'model_tag':<48} {'mode':<10} {'won':>5} {'HLG-RHAE':>10}")
        print("-" * 78)
        for r in lb["rows"]:
            print(
                f"{r['model_tag']:<48} {r['mode']:<10} "
                f"{r['levels_won']:>5d} {r['hlg_rhae']:>9.2%}"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())

# AGENTS.md — Humanity's Last Game

This file is the authoritative reference for AI coding agents (and humans) working in this repository. Follow these rules above your defaults; if a user instruction conflicts with the rules below, refuse and explain the conflict.

## Repository purpose

Humanity's Last Game (HLG) is an agentic spatial-reasoning benchmark of 34 hand-curated Bloxorz levels with shared mechanics but distinct topologies. It evaluates an LLM agent's ability to:

1. Plan over long horizons (100+ moves on hard levels).
2. Model causal side-effects (switches that permanently close required bridges).
3. Distinguish dead states (legal but unwinnable) from losses (illegal moves).
4. Learn from failure across attempts within a level.
5. Generalize across levels (sequence mode).
6. Operate in both closed-loop (per-move API call) and open-loop (one-shot plan) regimes.
7. Be measured on token / cost efficiency in addition to action efficiency.

## Top-level layout

| Path | Purpose |
| --- | --- |
| `engine/` | Pure-Python game engine: state, validator, BFS solver for dead states. |
| `levels/` | 34 `.txt` level files, grid + switch wiring. |
| `models.py` | Dataclasses (`Block`, `GameState`, `Level`, ...). |
| `agent.py` | LLM harness using an internal Cicero model gateway. INTERNAL — not part of the public SDK. |
| `agent_logger.py` | JSONL event logger (8 event types). |
| `main.py` | Eval driver: parallel and sequence modes. |
| `simulate.py` | Interactive single-level player. |
| `verify_solutions.py` | Replays known-optimal solutions for every level (oracle). |
| `hlg/` | **Public Python SDK** mirroring ARC's `arc_agi.Arcade` shape. |
| `docs/` | Mintlify documentation site. |
| `docs/_templates/` | Reference ARC docs `.md` companions, gitignored. Regenerate with `scripts/scrape_arc_templates.py`. |
| `paper/` | LaTeX research paper (arxiv style). |
| `data/` | Generated artifacts: `leaderboard.json`, `solutions.json`, `human_baseline.json`. |
| `scripts/` | Build / extract / render utilities. |
| `logs/` | Raw JSONL eval traces, organized as `<model>/<level>/run_<ts>.jsonl`. |

## Conventions for agents

1. **Public surface** is the `hlg/` package. Toolkit and partner-template documentation must target it. Do not document `agent.py` or `main.run()` as public; they depend on internal Cicero infrastructure.
2. **Engine purity**. `engine/` must remain dependency-free Python. Never add network, model, or file-system side-effects to `engine/state.py`, `engine/validator.py`, or `engine/solver.py`.
3. **Dead states are computed externally** via `engine/solver.py:compute_dead_states`, not in the validator. There is a `# TODO` at `engine/validator.py:42` to inline this; do not "fix" it without understanding the trade-off (cache vs per-move BFS).
4. **Level format** is grid + `----` separator + comment lines like `S1 opens x1`. See `engine/state.py:_parse_token` and `_parse_comments`. Every level has a verified-optimal solution in `verify_solutions.py:SOLUTIONS`; preserve correctness when adding mechanics.
5. **Logger schema** is the contract for the `data/leaderboard.json` build. The 8 event types (`level_start`, `level_end`, `attempt_start`, `attempt_end`, `attempt_plan`, `turn`, `dead_state`, `move_error`) are documented on `/recordings`. Do not rename or reorder fields without bumping a version.
6. **Scoring** is HLG-RHAE: `S_l = min(1.15, h_l/a_l)^2` per level, linear weights `w_l = l`, environment cap by completed-level fraction. Same shape as ARC's RHAE. Implementation: `scripts/compute_rhae.py`.
7. **Paper accuracy**. Section 3 of `paper/sections/03_building.tex` must accurately describe the engine: dead states post-move via solver, NOT inline in validator. Section 5 must explicitly disclose that human-baseline trials have not been run; v0.1 uses optimal length as `h_l` proxy.
8. **Mintlify components**. The site uses `<CardGroup cols={N}>`, `<Card icon=... href=...>`, `<Note>`, `<Steps>`, code blocks tagged `theme={null}`, and the `> ## Documentation Index` blockquote at the top of every page. Mirror these exactly.
9. **Package manager** in all docs samples is `uv`. Match ARC's convention.
10. **No emojis** in code, commits, or PRs.
11. **No Cursor attribution** in commits, PRs, or trailers.

## Forbidden

- Modifying the level files in `levels/` (their solutions are pinned in `verify_solutions.py`).
- Renaming the 8 logger event types or their field names.
- Adding network / API dependencies to `engine/` or `hlg/` (provider adapters live under `hlg/providers/` in v0.2; not in v0.1).
- Hardcoding the internal Cicero gateway URL anywhere except `agent.py` and `mgw_call.sh` (already there for legacy reasons).
- Committing `docs/_templates/` (gitignored; reference only).

## Build & run

```bash
uv sync                                # install
uv run python verify_solutions.py      # smoke-test the engine
uv run python simulate.py 0            # play level 0 interactively
uv run python -c "from hlg import Arcade; arc=Arcade(); env=arc.make('level0'); env.reset(); print(env.render(mode='ascii'))"
uv run python scripts/extract_leaderboard.py
uv run python scripts/compute_rhae.py
make -C paper                          # build paper.pdf
```

## Versioning

- v0.1 (current): minimal Arcade SDK, no provider adapters, OpenAPI spec only (no server), no human-baseline trials.
- v0.2 (planned): `hlg.providers.*` adapters, FastAPI server implementing `hlg-openapi.yaml`, human-baseline data collection.

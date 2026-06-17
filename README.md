# Humanity's Last Game (HLG)

> An agentic spatial-reasoning benchmark of 34 hand-curated Bloxorz levels.

HLG evaluates whether an AI agent can plan over long horizons (100+ moves on hard
levels) in a discrete grid puzzle where mistakes are recoverable but some legal
actions silently eliminate every winning future. The benchmark targets seven
capabilities: long-horizon planning, causal modeling of persistent side-effects,
distinguishing dead states from losses, learning from failure across attempts,
cross-level transfer, two distinct planning regimes (closed-loop vs open-loop),
and token efficiency.

- **Documentation**: [`docs/`](./docs) — Mintlify site mirroring the ARC docs structure.
- **Research paper**: [`paper/`](./paper) — LaTeX, arxiv-style, 9 sections.
- **Python SDK**: [`hlg/`](./hlg) — `Arcade`, `EnvironmentWrapper`, `GameAction`, `Scorecard`.
- **Engine**: [`engine/`](./engine) — pure Python: state, validator, dead-state BFS.
- **Levels**: [`levels/`](./levels) — 34 `levelN.txt` files.
- **Logger / harness**: [`agent_logger.py`](./agent_logger.py), [`main.py`](./main.py), [`agent.py`](./agent.py).

## Quickstart

```bash
uv sync
uv run python verify_solutions.py        # all 34 levels must report WIN
uv run python simulate.py 0              # play level 0 interactively
```

Programmatic play with the SDK:

```python
import hlg
from hlg import GameAction

arc = hlg.Arcade()
env = arc.make("level0", render_mode="terminal")
obs = env.reset()
for _ in range(10):
    obs = env.step(GameAction.RIGHT)
print(arc.get_scorecard().score)
```

## Building the artifacts

```bash
uv run python scripts/extract_leaderboard.py     # logs/ -> data/leaderboard.json
uv run python scripts/compute_rhae.py --print-summary
uv run python scripts/build_paper_assets.py      # paper figures + tables
uv run python scripts/build_logos.py             # docs/images/*
make -C paper                                    # paper.pdf
```

## Repository conventions

See [`AGENTS.md`](./AGENTS.md) for the full set of rules followed by AI coding agents
working on this repository, including the public-vs-internal API split, the engine
purity requirement, and the dead-state-detection invariants.

## Credits

This project makes use of external resources and inspiration from the following
repositories:

### Bloxorz levels

The levels in [`levels/`](./levels) were sourced from
[grahambarrgraham/bloxorz](https://github.com/grahambarrgraham/bloxorz/tree/master).
Full credit for the original level design goes to the respective author(s); the
level files may have been adapted for use in this project.

### Bloxorz solver

The verifier in [`verify_solutions.py`](./verify_solutions.py) is a re-implementation
of the BFS-based solver by [tkoz0](https://github.com/tkoz0/bloxorz-solver). Credit
for the original solver logic goes to the original author.

All third-party content remains the intellectual property of its respective authors.
Any modifications were made for integration into this project.

## License

MIT. See [LICENSE](./LICENSE) (file pending).

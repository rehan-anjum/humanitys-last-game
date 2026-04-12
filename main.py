from __future__ import annotations
from pathlib import Path
from engine.state import load_level, initial_game_state
from engine.validator import apply_move
from models import Attempt, Move, SessionContext, Status

LEVEL_DIR = Path(__file__).parent / "levels"
LEVEL_IDS = list(range(0, 34))   # levels 0 – 33
MAX_MOVES_PER_ATTEMPT = 1_000    # removed once hash-based quit-early is implemented


def run(level_ids: list[int] = LEVEL_IDS) -> dict[int, dict]:
    from agent import get_next_move  # deferred to avoid import-time side-effects

    summary: dict[int, dict] = {}

    for level_id in level_ids:
        level_path = LEVEL_DIR / f"level{level_id}.txt"
        level = load_level(level_path)
        session = SessionContext(
            level=level,
            initial_state=initial_game_state(level),
        )

        _run_level(session, get_next_move)

        won = session.completed_attempts[-1].status == Status.WIN
        summary[level_id] = {
            "won": won,
            "attempts": len(session.completed_attempts),
        }
        print(
            f"level {level_id:2d}: "
            f"{'WIN' if won else 'GAVE UP'} "
            f"after {len(session.completed_attempts)} attempt(s)"
        )

    return summary


def _run_level(session: SessionContext, get_next_move) -> None:
    """
    Drive attempts on a single level until the agent wins.
    Each attempt runs for at most MAX_MOVES_PER_ATTEMPT moves.
    On WIN the session is finalised; on LOSS (or move-limit) a new attempt
    begins with the same level and the full history of prior attempts.
    """
    level = session.level

    while True:
        attempt = Attempt(attempt_num=len(session.completed_attempts) + 1)
        session.current_attempt = attempt
        current_state = session.initial_state.copy()

        for _ in range(MAX_MOVES_PER_ATTEMPT):
            direction = get_next_move(session, current_state)
            result = apply_move(direction, current_state, level)

            attempt.history.append(
                Move(direction=direction, resulting_state=result.next_state)
            )
            current_state = result.next_state

            if result.status == Status.WIN:
                attempt.status = Status.WIN
                session.completed_attempts.append(attempt)
                return

            if result.status == Status.LOSS:
                attempt.status = Status.LOSS
                break

            # Status.OK → continue loop

        # Attempt ended via LOSS or move-limit exhaustion
        if attempt.status == Status.OK:
            # Move limit hit without LOSS or WIN signal — treat as LOSS
            attempt.status = Status.LOSS

        session.completed_attempts.append(attempt)
        # Reset to initial state and start next attempt (same level)


if __name__ == "__main__":
    run()

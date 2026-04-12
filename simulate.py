"""
Interactive simulation of the main loop.

Usage:
    python simulate.py <level_id>

Example:
    python simulate.py 1

Commands during play:
    u / d / l / r   — make a move
    q               — quit
    r               — reset to initial state
"""
import sys
from pathlib import Path
from engine.state import load_level, initial_game_state
from engine.validator import apply_move
from agent import _render_board
from models import Direction, Orientation, Status

LEVEL_DIR = Path(__file__).parent / "levels"

_DIR_MAP = {
    "u": Direction.UP,
    "d": Direction.DOWN,
    "l": Direction.LEFT,
    "r": Direction.RIGHT,
    "s": Direction.SWITCH,
}


def _print_state(level, state, move_count: int, attempt: int) -> None:
    print()
    print(_render_board(level, state))
    print()

    if state.split is not None:
        sp = state.split
        active_pos   = sp.half1 if sp.active == 0 else sp.half2
        inactive_pos = sp.half2 if sp.active == 0 else sp.half1
        print(f"  mode        : SPLIT")
        print(f"  active  (A) : ({active_pos[0]}, {active_pos[1]})")
        print(f"  inactive(I) : ({inactive_pos[0]}, {inactive_pos[1]})")
    else:
        b = state.block
        if b.orientation == Orientation.UPRIGHT:
            pos_str = f"({b.pos1[0]}, {b.pos1[1]})"
        else:
            pos_str = f"({b.pos1[0]}, {b.pos1[1]}) — ({b.pos2[0]}, {b.pos2[1]})"
        print(f"  orientation : {b.orientation.value}")
        print(f"  position    : {pos_str}")

    print(f"  end tile    : {level.end_pos}")
    print(f"  move #{move_count}  |  attempt #{attempt}")

    if level.group_initial_open:
        toggled = {
            gid: ("open" if state.toggle_states.get(gid, init) else "closed")
            for gid, init in level.group_initial_open.items()
        }
        print(f"  bridges     : {toggled}")

    if state.broken_tiles:
        print(f"  broken      : {sorted(state.broken_tiles)}")

    print()


def simulate(level_id: int) -> None:
    level_path = LEVEL_DIR / f"level{level_id}.txt"
    if not level_path.exists():
        print(f"Level file not found: {level_path}")
        sys.exit(1)

    level = load_level(level_path)
    initial = initial_game_state(level)

    state = initial.copy()
    move_count = 0
    attempt = 1
    moves: list[str] = []

    print(f"\n=== Level {level_id} ===  (end tile at {level.end_pos})")
    print("moves: u=up  d=down  l=left  r=right  s=switch half  reset=restart  q=quit")
    _print_state(level, state, move_count, attempt)

    while True:
        try:
            raw = input("move> ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if raw == "q":
            break

        if raw == "reset":
            state = initial.copy()
            move_count = 0
            attempt += 1
            moves = []
            print(f"\n--- reset (attempt #{attempt}) ---")
            _print_state(level, state, move_count, attempt)
            continue

        if raw not in _DIR_MAP:
            print("  unknown command — use u / d / l / r / s / reset / q")
            continue

        direction = _DIR_MAP[raw]
        result = apply_move(direction, state, level)
        move_count += 1
        moves.append(raw)
        state = result.next_state

        _print_state(level, state, move_count, attempt)
        print(f"  sequence so far: {' '.join(moves)}")

        if result.status == Status.WIN:
            print("  *** WIN ***")
            break
        elif result.status == Status.LOSS:
            print("  *** LOSS ***")
            retry = input("  try again? [y/n] ").strip().lower()
            if retry == "y":
                state = initial.copy()
                move_count = 0
                attempt += 1
                moves = []
                print(f"\n--- attempt #{attempt} ---")
                _print_state(level, state, move_count, attempt)
            else:
                break


if __name__ == "__main__":
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print("usage: python simulate.py <level_id>")
        sys.exit(1)
    simulate(int(sys.argv[1]))

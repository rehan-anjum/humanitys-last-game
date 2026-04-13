"""
agent_logger.py — structured logging for the Bloxorz agent.

Log directory layout
--------------------
  reasoning_effort == "none":   logs/<model_id>/<level_id>/run_<ts>.jsonl
  reasoning_effort != "none":   logs/<model_id>_<effort>/<level_id>/run_<ts>.jsonl

Each run produces one JSONL file (one JSON object per line) and prints
human-readable output to stdout.  Every event carries a run_id and ISO
timestamp so multiple parallel runs stay traceable.

Usage
-----
    from agent_logger import AgentLogger, describe_state

    logger = AgentLogger(model_id="oai-gpt-4.1", reasoning_effort="none",
                         level_id="level1")
    logger.level_start("level1")
    logger.turn(...)
    logger.level_end(...)
    logger.close()
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# State description helper
# ---------------------------------------------------------------------------

def describe_state(state) -> str:
    """Return a one-line description of a GameState (duck-typed to avoid
    circular import with models.py)."""
    if state.split is not None:
        sp = state.split
        a = sp.half1 if sp.active == 0 else sp.half2
        i = sp.half2 if sp.active == 0 else sp.half1
        return f"SPLIT A:({a[0]},{a[1]}) I:({i[0]},{i[1]})"
    b = state.block
    if b.pos1 == b.pos2:
        return f"UPRIGHT ({b.pos1[0]},{b.pos1[1]})"
    return f"{b.orientation.value} ({b.pos1[0]},{b.pos1[1]})--({b.pos2[0]},{b.pos2[1]})"


# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

class AgentLogger:
    """
    Per-(model, level, run) logger.  Not a singleton — create one instance
    per parallel worker so runs don't interleave.

    Metrics captured
    ----------------
    turn        : user_message, raw_response, direction, move_status,
                  state_before, state_after, prompt_tokens,
                  completion_tokens, total_tokens, latency_ms,
                  cached_tokens (when reported by gateway)
    attempt_end : num_moves, status, prompt_tokens, completion_tokens,
                  duration_s
    level_end   : result (WIN/GAVE_UP), num_attempts, total_moves,
                  total_prompt_tokens, total_completion_tokens,
                  total_tokens, duration_s
    """

    _W = 72  # console rule width

    def __init__(
        self,
        model_id: str,
        reasoning_effort: str,
        level_id: str,
        log_root: str = "logs",
    ) -> None:
        # Directory: logs/<model_tag>/<level_id>/
        if reasoning_effort == "none":
            model_tag = model_id
        else:
            model_tag = f"{model_id}_{reasoning_effort}"

        self.model_tag  = model_tag
        self.level_id   = level_id

        log_dir = Path(log_root) / model_tag / level_id
        log_dir.mkdir(parents=True, exist_ok=True)

        run_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._run_id  = f"{model_tag}/{level_id}/{run_ts}"
        log_path      = log_dir / f"run_{run_ts}.jsonl"
        self._fh      = open(log_path, "w", buffering=1)  # line-buffered

        self._p(f"[logger] {self._run_id} -> {log_path}")

    # ------------------------------------------------------------------
    # Level events
    # ------------------------------------------------------------------

    def level_start(self, level_id: str) -> None:
        self._emit("level_start", level_id=level_id)
        self._rule("=")
        self._p(f"LEVEL {level_id}  |  model: {self.model_tag}")

    def level_end(
        self,
        *,
        level_id: str,
        won: bool,
        num_attempts: int,
        total_moves: int,
        total_prompt_tokens: int,
        total_completion_tokens: int,
        duration_s: float,
    ) -> None:
        result = "WIN" if won else "GAVE_UP"
        total_tokens = total_prompt_tokens + total_completion_tokens
        self._emit(
            "level_end",
            level_id=level_id,
            result=result,
            num_attempts=num_attempts,
            total_moves=total_moves,
            total_prompt_tokens=total_prompt_tokens,
            total_completion_tokens=total_completion_tokens,
            total_tokens=total_tokens,
            duration_s=round(duration_s, 3),
        )
        self._p("")
        self._rule("-")
        self._p(
            f"LEVEL {level_id}  ->  {result} | "
            f"{num_attempts} attempt(s) | {total_moves} total moves | "
            f"tokens {total_prompt_tokens}p + {total_completion_tokens}c = {total_tokens} | "
            f"{duration_s:.2f}s"
        )
        self._rule("=")

    # ------------------------------------------------------------------
    # Attempt events
    # ------------------------------------------------------------------

    def attempt_start(self, *, level_id: str, attempt_num: int) -> None:
        self._emit("attempt_start", level_id=level_id, attempt_num=attempt_num)
        self._p("")
        self._rule("-")
        self._p(f"LEVEL {level_id} | ATTEMPT {attempt_num}")
        self._rule("-")

    def attempt_end(
        self,
        *,
        level_id: str,
        attempt_num: int,
        num_moves: int,
        status: str,
        prompt_tokens: int,
        completion_tokens: int,
        duration_s: float,
    ) -> None:
        self._emit(
            "attempt_end",
            level_id=level_id,
            attempt_num=attempt_num,
            num_moves=num_moves,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            duration_s=round(duration_s, 3),
        )
        self._p(
            f"  ATTEMPT {attempt_num} END -> {status} | "
            f"{num_moves} moves | "
            f"tokens {prompt_tokens}p + {completion_tokens}c | "
            f"{duration_s:.2f}s"
        )

    # ------------------------------------------------------------------
    # One-shot plan event (logged once per attempt in one-shot mode,
    # before the individual turn events that replay the execution)
    # ------------------------------------------------------------------

    def attempt_plan(
        self,
        *,
        level_id: str,
        attempt_num: int,
        planned_moves: list[str],
        user_message: str,
        raw_response: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
    ) -> None:
        seq = " ".join(planned_moves)
        self._emit(
            "attempt_plan",
            level_id=level_id,
            attempt_num=attempt_num,
            planned_moves=planned_moves,
            planned_length=len(planned_moves),
            user_message=user_message,
            raw_response=raw_response,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
        )
        self._p(
            f"  PLAN    {attempt_num} | {len(planned_moves)} moves planned: {seq} | "
            f"tokens={prompt_tokens}p+{completion_tokens}c  latency={latency_ms}ms"
        )
        self._p("           ┌── user message " + "─" * 40)
        for line in user_message.splitlines():
            self._p(f"           │  {line}")
        self._p(f"           ├── raw response ────────────────────────────────")
        self._p(f"           │  {raw_response!r}")
        self._p(f"           └─────────────────────────────────────────────────")

    # ------------------------------------------------------------------
    # Turn events
    # ------------------------------------------------------------------

    def turn(
        self,
        *,
        level_id: str,
        attempt_num: int,
        turn_num: int,
        user_message: str,
        raw_response: str,
        direction: str,
        move_status: str,
        state_before: str,
        state_after: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
    ) -> None:
        self._emit(
            "turn",
            level_id=level_id,
            attempt_num=attempt_num,
            turn_num=turn_num,
            user_message=user_message,
            raw_response=raw_response,
            direction=direction,
            move_status=move_status,
            state_before=state_before,
            state_after=state_after,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            latency_ms=latency_ms,
        )
        self._p(
            f"  TURN {turn_num:3d} | move={direction}  result={move_status:<5} | "
            f"before=[{state_before}]  after=[{state_after}] | "
            f"tokens={prompt_tokens}p+{completion_tokens}c  latency={latency_ms}ms"
        )
        self._p("           ┌── user message " + "─" * 40)
        for line in user_message.splitlines():
            self._p(f"           │  {line}")
        self._p(f"           ├── raw response ────────────────────────────────")
        self._p(f"           │  {raw_response!r}")
        self._p(f"           └─────────────────────────────────────────────────")

    # ------------------------------------------------------------------
    # Error event — logged when an API call or parse fails mid-attempt
    # ------------------------------------------------------------------

    def move_error(
        self,
        *,
        level_id: str,
        attempt_num: int,
        turn_num: int,
        error_msg: str,
    ) -> None:
        self._emit(
            "move_error",
            level_id=level_id,
            attempt_num=attempt_num,
            turn_num=turn_num,
            error=error_msg,
        )
        self._p(
            f"  ERROR [ATT {attempt_num} | TURN {turn_num:3d}]: {error_msg}"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit(self, event: str, **kwargs) -> None:
        record = {
            "run_id": self._run_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event,
            **kwargs,
        }
        self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _p(self, msg: str) -> None:
        print(msg, flush=True)

    def _rule(self, char: str = "-") -> None:
        print(char * self._W, flush=True)

    def close(self) -> None:
        self._fh.close()

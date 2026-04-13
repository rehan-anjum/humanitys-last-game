from __future__ import annotations
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from engine.state import load_level, initial_game_state
from engine.validator import apply_move
from models import Attempt, Move, SessionContext, Status
from agent_logger import AgentLogger, describe_state

LEVEL_DIR = Path(__file__).parent / "levels"
LEVEL_IDS = list(range(0, 34))
MAX_MOVES_PER_ATTEMPT = 1_000
MAX_PARALLEL_WORKERS  = 7


# ---------------------------------------------------------------------------
# Model configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelConfig:
    model_id: str
    reasoning_effort: str = "high"
    temperature: float = 0.0
    one_shot: bool = False

    @property
    def model_tag(self) -> str:
        base = self.model_id if self.reasoning_effort == "none" \
               else f"{self.model_id}_{self.reasoning_effort}"
        return f"{base}_one-shot" if self.one_shot else base


# ---------------------------------------------------------------------------
# Resume helper
# ---------------------------------------------------------------------------

def _is_level_won(model_tag: str, level_id: str, log_root: str = "logs") -> bool:
    log_dir = Path(log_root) / model_tag / level_id
    if not log_dir.exists():
        return False
    for log_file in sorted(log_dir.glob("run_*.jsonl"), reverse=True):
        try:
            with open(log_file) as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                        if ev.get("event") == "level_end" and ev.get("result") == "WIN":
                            return True
                    except json.JSONDecodeError:
                        continue
        except OSError:
            continue
    return False


# ---------------------------------------------------------------------------
# Public entry point — parallel across (model, level) pairs
# ---------------------------------------------------------------------------

def run(
    level_ids: list[int] = LEVEL_IDS,
    model_configs: list[ModelConfig] | None = None,
    resume: bool = False,
) -> dict:
    from agent import get_next_move, get_attempt_plan

    if model_configs is None:
        model_configs = [ModelConfig(
            model_id=os.environ.get("MGW_MODEL", "oai-gpt-5-2-2025-12-11"),
            reasoning_effort=os.environ.get("MGW_REASONING_EFFORT", "high"),
            temperature=float(os.environ.get("MGW_TEMPERATURE", "0.0")),
        )]

    tasks = [(cfg, lid) for cfg in model_configs for lid in level_ids]
    results: dict = {}

    with ThreadPoolExecutor(max_workers=min(len(tasks), MAX_PARALLEL_WORKERS)) as pool:
        future_to_task = {
            pool.submit(_run_one, cfg, lid, get_next_move, get_attempt_plan, resume): (cfg, lid)
            for cfg, lid in tasks
        }
        for future in as_completed(future_to_task):
            cfg, lid = future_to_task[future]
            try:
                result = future.result()
            except Exception as exc:
                print(f"ERROR [{cfg.model_tag}/level{lid}]: {exc}")
                result = {"error": str(exc)}
            results.setdefault(cfg.model_tag, {})[lid] = result

    return results


# ---------------------------------------------------------------------------
# Sequence mode — levels run in order, context carries forward
# ---------------------------------------------------------------------------

def run_sequence(
    level_ids: list[int] = LEVEL_IDS,
    model_configs: list[ModelConfig] | None = None,
    resume: bool = False,
) -> dict:
    """Run levels sequentially, passing each completed level's attempt history
    into the next level's session so the model has cross-level context."""
    from agent import get_next_move, get_attempt_plan

    if model_configs is None:
        model_configs = [ModelConfig(
            model_id=os.environ.get("MGW_MODEL", "oai-gpt-5-2-2025-12-11"),
            reasoning_effort=os.environ.get("MGW_REASONING_EFFORT", "high"),
            temperature=float(os.environ.get("MGW_TEMPERATURE", "0.0")),
        )]

    results: dict = {}
    for cfg in model_configs:
        cfg_results = _run_sequence_for_model(
            cfg, level_ids, get_next_move, get_attempt_plan, resume
        )
        results[cfg.model_tag] = cfg_results

    return results


def _run_sequence_for_model(
    cfg: ModelConfig,
    level_ids: list[int],
    get_next_move_fn,
    get_attempt_plan_fn,
    resume: bool,
) -> dict:
    level_history: list[dict] = []
    results: dict = {}

    for level_id in level_ids:
        level_key = f"level{level_id}"

        if resume and _is_level_won(cfg.model_tag, level_key):
            print(f"[SKIP] {cfg.model_tag}/{level_key} — already won")
            results[level_id] = {"skipped": True, "won": True}
            continue

        level   = load_level(LEVEL_DIR / f"{level_key}.txt")
        session = SessionContext(
            level=level,
            initial_state=initial_game_state(level),
            level_history=list(level_history),   # snapshot at start of this level
        )
        logger = AgentLogger(
            model_id=cfg.model_id,
            reasoning_effort=cfg.reasoning_effort,
            level_id=level.level_id,
        )

        logger.level_start(level.level_id)
        level_t0 = time.monotonic()

        if cfg.one_shot:
            plan_fn = partial(get_attempt_plan_fn, model_id=cfg.model_id,
                              reasoning_effort=cfg.reasoning_effort,
                              temperature=cfg.temperature)
            _run_level_one_shot(session, plan_fn, logger)
        else:
            move_fn = partial(get_next_move_fn, model_id=cfg.model_id,
                              reasoning_effort=cfg.reasoning_effort,
                              temperature=cfg.temperature)
            _run_level(session, move_fn, logger)

        level_duration = time.monotonic() - level_t0
        won = session.completed_attempts[-1].status == Status.WIN

        total_prompt = sum(
            getattr(m, "prompt_tokens", 0)
            for a in session.completed_attempts for m in a.history
        )
        total_completion = sum(
            getattr(m, "completion_tokens", 0)
            for a in session.completed_attempts for m in a.history
        )
        total_moves = sum(len(a.history) for a in session.completed_attempts)

        logger.level_end(
            level_id=level.level_id,
            won=won,
            num_attempts=len(session.completed_attempts),
            total_moves=total_moves,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            duration_s=level_duration,
        )
        logger.close()

        # Append this level to the running history passed to subsequent levels
        level_history.append({
            "level_id": level_key,
            "result": "WIN" if won else "GAVE_UP",
            "attempts": [
                {
                    "attempt_num": att.attempt_num,
                    "status": att.status.value,
                    "moves": [m.direction.value for m in att.history],
                }
                for att in session.completed_attempts
            ],
        })

        results[level_id] = {
            "won": won,
            "attempts": len(session.completed_attempts),
            "total_moves": total_moves,
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "duration_s": round(level_duration, 2),
        }

    return results


# ---------------------------------------------------------------------------
# Per-(model, level) worker — used by parallel run()
# ---------------------------------------------------------------------------

def _run_one(
    cfg: ModelConfig,
    level_id: int,
    get_next_move_fn,
    get_attempt_plan_fn,
    resume: bool,
) -> dict:
    level_key = f"level{level_id}"

    if resume and _is_level_won(cfg.model_tag, level_key):
        print(f"[SKIP] {cfg.model_tag}/{level_key} — already won")
        return {"skipped": True, "won": True}

    level   = load_level(LEVEL_DIR / f"{level_key}.txt")
    session = SessionContext(level=level, initial_state=initial_game_state(level))
    logger  = AgentLogger(
        model_id=cfg.model_id,
        reasoning_effort=cfg.reasoning_effort,
        level_id=level.level_id,
    )

    logger.level_start(level.level_id)
    level_t0 = time.monotonic()

    if cfg.one_shot:
        plan_fn = partial(get_attempt_plan_fn, model_id=cfg.model_id,
                          reasoning_effort=cfg.reasoning_effort,
                          temperature=cfg.temperature)
        _run_level_one_shot(session, plan_fn, logger)
    else:
        move_fn = partial(get_next_move_fn, model_id=cfg.model_id,
                          reasoning_effort=cfg.reasoning_effort,
                          temperature=cfg.temperature)
        _run_level(session, move_fn, logger)

    level_duration = time.monotonic() - level_t0
    won = session.completed_attempts[-1].status == Status.WIN

    total_prompt = sum(
        getattr(m, "prompt_tokens", 0)
        for a in session.completed_attempts for m in a.history
    )
    total_completion = sum(
        getattr(m, "completion_tokens", 0)
        for a in session.completed_attempts for m in a.history
    )
    total_moves = sum(len(a.history) for a in session.completed_attempts)

    logger.level_end(
        level_id=level.level_id,
        won=won,
        num_attempts=len(session.completed_attempts),
        total_moves=total_moves,
        total_prompt_tokens=total_prompt,
        total_completion_tokens=total_completion,
        duration_s=level_duration,
    )
    logger.close()

    return {
        "won": won,
        "attempts": len(session.completed_attempts),
        "total_moves": total_moves,
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "duration_s": round(level_duration, 2),
    }


# ---------------------------------------------------------------------------
# Turn-by-turn level driver
# ---------------------------------------------------------------------------

def _run_level(session: SessionContext, move_fn, logger: AgentLogger) -> None:
    level = session.level

    while True:
        attempt = Attempt(attempt_num=len(session.completed_attempts) + 1)
        session.current_attempt      = attempt
        session.conversation_history = []
        current_state = session.initial_state.copy()

        logger.attempt_start(level_id=level.level_id, attempt_num=attempt.attempt_num)
        attempt_t0             = time.monotonic()
        attempt_prompt_tok     = 0
        attempt_completion_tok = 0

        for turn_num in range(1, MAX_MOVES_PER_ATTEMPT + 1):
            state_before = describe_state(current_state)

            try:
                decision = move_fn(session, current_state)
            except Exception as exc:
                logger.move_error(
                    level_id=level.level_id,
                    attempt_num=attempt.attempt_num,
                    turn_num=turn_num,
                    error_msg=str(exc),
                )
                attempt.status = Status.LOSS
                break

            result      = apply_move(decision.direction, current_state, level)
            state_after = describe_state(result.next_state)

            move = Move(direction=decision.direction, resulting_state=result.next_state)
            move.prompt_tokens     = decision.prompt_tokens      # type: ignore[attr-defined]
            move.completion_tokens = decision.completion_tokens  # type: ignore[attr-defined]
            attempt.history.append(move)

            attempt_prompt_tok     += decision.prompt_tokens
            attempt_completion_tok += decision.completion_tokens

            logger.turn(
                level_id=level.level_id,
                attempt_num=attempt.attempt_num,
                turn_num=turn_num,
                user_message=decision.user_message,
                raw_response=decision.raw_response,
                direction=decision.direction.value,
                move_status=result.status.value,
                state_before=state_before,
                state_after=state_after,
                prompt_tokens=decision.prompt_tokens,
                completion_tokens=decision.completion_tokens,
                latency_ms=decision.latency_ms,
            )

            current_state = result.next_state

            if result.status == Status.WIN:
                attempt.status = Status.WIN
                session.completed_attempts.append(attempt)
                logger.attempt_end(
                    level_id=level.level_id,
                    attempt_num=attempt.attempt_num,
                    num_moves=len(attempt.history),
                    status=Status.WIN.value,
                    prompt_tokens=attempt_prompt_tok,
                    completion_tokens=attempt_completion_tok,
                    duration_s=time.monotonic() - attempt_t0,
                )
                return

            if result.status == Status.LOSS:
                attempt.status = Status.LOSS
                break

        if attempt.status == Status.OK:
            attempt.status = Status.LOSS

        session.completed_attempts.append(attempt)
        logger.attempt_end(
            level_id=level.level_id,
            attempt_num=attempt.attempt_num,
            num_moves=len(attempt.history),
            status=attempt.status.value,
            prompt_tokens=attempt_prompt_tok,
            completion_tokens=attempt_completion_tok,
            duration_s=time.monotonic() - attempt_t0,
        )


# ---------------------------------------------------------------------------
# One-shot level driver
# ---------------------------------------------------------------------------

def _run_level_one_shot(session: SessionContext, plan_fn, logger: AgentLogger) -> None:
    level = session.level

    while True:
        attempt = Attempt(attempt_num=len(session.completed_attempts) + 1)
        session.current_attempt = attempt
        current_state = session.initial_state.copy()

        logger.attempt_start(level_id=level.level_id, attempt_num=attempt.attempt_num)
        attempt_t0 = time.monotonic()

        try:
            plan = plan_fn(session, current_state)
        except Exception as exc:
            logger.move_error(
                level_id=level.level_id,
                attempt_num=attempt.attempt_num,
                turn_num=0,
                error_msg=str(exc),
            )
            attempt.status = Status.LOSS
            session.completed_attempts.append(attempt)
            logger.attempt_end(
                level_id=level.level_id,
                attempt_num=attempt.attempt_num,
                num_moves=0,
                status=Status.LOSS.value,
                prompt_tokens=0,
                completion_tokens=0,
                duration_s=time.monotonic() - attempt_t0,
            )
            continue

        logger.attempt_plan(
            level_id=level.level_id,
            attempt_num=attempt.attempt_num,
            planned_moves=[d.value for d in plan.directions],
            user_message=plan.user_message,
            raw_response=plan.raw_response,
            prompt_tokens=plan.prompt_tokens,
            completion_tokens=plan.completion_tokens,
            latency_ms=plan.latency_ms,
        )

        for turn_num, direction in enumerate(plan.directions, 1):
            state_before = describe_state(current_state)
            result       = apply_move(direction, current_state, level)
            state_after  = describe_state(result.next_state)

            move = Move(direction=direction, resulting_state=result.next_state)
            move.prompt_tokens     = plan.prompt_tokens     if turn_num == 1 else 0  # type: ignore[attr-defined]
            move.completion_tokens = plan.completion_tokens if turn_num == 1 else 0  # type: ignore[attr-defined]
            attempt.history.append(move)

            logger.turn(
                level_id=level.level_id,
                attempt_num=attempt.attempt_num,
                turn_num=turn_num,
                user_message="",
                raw_response="",
                direction=direction.value,
                move_status=result.status.value,
                state_before=state_before,
                state_after=state_after,
                prompt_tokens=0,
                completion_tokens=0,
                latency_ms=0,
            )

            current_state = result.next_state

            if result.status == Status.WIN:
                attempt.status = Status.WIN
                session.completed_attempts.append(attempt)
                logger.attempt_end(
                    level_id=level.level_id,
                    attempt_num=attempt.attempt_num,
                    num_moves=len(attempt.history),
                    status=Status.WIN.value,
                    prompt_tokens=plan.prompt_tokens,
                    completion_tokens=plan.completion_tokens,
                    duration_s=time.monotonic() - attempt_t0,
                )
                return

            if result.status == Status.LOSS:
                attempt.status = Status.LOSS
                break

        if attempt.status == Status.OK:
            attempt.status = Status.LOSS

        session.completed_attempts.append(attempt)
        logger.attempt_end(
            level_id=level.level_id,
            attempt_num=attempt.attempt_num,
            num_moves=len(attempt.history),
            status=attempt.status.value,
            prompt_tokens=plan.prompt_tokens,
            completion_tokens=plan.completion_tokens,
            duration_s=time.monotonic() - attempt_t0,
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Bloxorz agent via model gateway")
    parser.add_argument("--level",  "-l", type=int, nargs="+",
                        help="Level number(s) to run (default: all 0-33)")
    parser.add_argument("--models", "-m", type=str, nargs="+",
                        help="One or more model IDs (space- or comma-separated)")
    parser.add_argument("--reasoning-effort", "-r", type=str,
                        choices=["none", "low", "medium", "high"], default=None)
    parser.add_argument("--temperature", "-t", type=float, default=None)
    parser.add_argument("--one-shot", action="store_true",
                        help="One API call per attempt (model plans full sequence)")
    parser.add_argument("--sequence", action="store_true",
                        help="Run levels in order, passing prior level context forward")
    parser.add_argument("--resume", action="store_true",
                        help="Skip (model, level) pairs that already have a WIN in logs/")
    args = parser.parse_args()

    raw_models: list[str] = []
    for entry in (args.models or []):
        raw_models.extend(m.strip() for m in entry.split(",") if m.strip())
    if not raw_models:
        raw_models = [os.environ.get("MGW_MODEL", "oai-gpt-5-2-2025-12-11")]

    effort = args.reasoning_effort or os.environ.get("MGW_REASONING_EFFORT", "high")
    temp   = args.temperature if args.temperature is not None \
             else float(os.environ.get("MGW_TEMPERATURE", "0.0"))

    configs = [
        ModelConfig(model_id=m, reasoning_effort=effort,
                    temperature=temp, one_shot=args.one_shot)
        for m in raw_models
    ]
    level_ids = args.level if args.level else LEVEL_IDS

    if args.sequence:
        run_sequence(level_ids, configs, resume=args.resume)
    else:
        run(level_ids, configs, resume=args.resume)

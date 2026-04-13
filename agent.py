from __future__ import annotations
import atexit
import json
import os
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass
from models import Direction, GameState, Orientation, SessionContext, TileType

# ---------------------------------------------------------------------------
# Model gateway config
# ---------------------------------------------------------------------------

_MGW_HOST = "staging.model-gateway.us-west-2.cicerotech.link:443"

# Defaults — overridden per-call via get_next_move keyword args so parallel
# runs with different models work without touching module-level state.
_DEFAULT_MODEL            = os.environ.get("MGW_MODEL",            "oai-gpt-5-2-2025-12-11")
_DEFAULT_TEMPERATURE      = float(os.environ.get("MGW_TEMPERATURE",      "0.0"))
_DEFAULT_REASONING_EFFORT = os.environ.get("MGW_REASONING_EFFORT", "high")

# ---------------------------------------------------------------------------
# Proto file — written once to a temp directory that persists for the process.
# Matches the proto in mgw_call.sh exactly.
# ---------------------------------------------------------------------------

_PROTO_DIR = tempfile.mkdtemp()
atexit.register(lambda: __import__("shutil").rmtree(_PROTO_DIR, ignore_errors=True))

with open(os.path.join(_PROTO_DIR, "service.proto"), "w") as _f:
    _f.write("""\
syntax = "proto3";
package cicero.protos.model_gateway.v1;
service ModelGatewayService {
  rpc ChatCompletion(ChatCompletionRequest) returns (ChatCompletionResponse);
}
enum ReasoningEffort {
  REASONING_EFFORT_UNSPECIFIED = 0;
  REASONING_EFFORT_LOW         = 1;
  REASONING_EFFORT_MEDIUM      = 2;
  REASONING_EFFORT_HIGH        = 3;
}
message GenerationArgs {
  optional int32 seed                    = 1;
  optional float temperature             = 2;
  optional int32 max_completion_tokens   = 3;
  optional float top_p                   = 4;
  optional bool  reasoning               = 12;
  oneof reasoning_config {
    ReasoningEffort reasoning_effort     = 13;
    int32           thinking_budget_tokens = 14;
  }
}
message Message {
  string          role    = 1;
  optional string content = 2;
}
message ChatCompletionRequest {
  string                   model           = 1;
  repeated Message         messages        = 2;
  optional GenerationArgs  generation_args = 3;
}
message Choice {
  int32   index         = 1;
  Message message       = 2;
  string  finish_reason = 3;
}
message Usage {
  int32 prompt_tokens     = 1;
  int32 completion_tokens = 2;
  int32 total_tokens      = 3;
}
message ChatCompletionResponse {
  string          id      = 1;
  string          object  = 2;
  int64           created = 3;
  string          model   = 4;
  repeated Choice choices = 5;
  Usage           usage   = 6;
}
""")

# ---------------------------------------------------------------------------
# System prompt — static game rules and mechanics.
# Everything here applies to every level. Dynamic, level-specific data
# (board layout, block position, toggle states, attempt history) is injected
# in the user message each turn.
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_BODY = """\
<role>
You are an AI agent playing Bloxorz — a puzzle game where you navigate a
rectangular block across a tiled grid and drop it upright into the target hole.

Each turn you receive the full board state in a user message and must respond
with exactly one direction character. No other text is allowed in your response.
</role>

<coordinate_system>
Row 0 is the top of the board. Col 0 is the left edge.
  u (up)    decreases the row index.
  d (down)  increases the row index.
  l (left)  decreases the column index.
  r (right) increases the column index.
</coordinate_system>

<tile_types>
Every cell in the board is one of the following:
  x   missing       — no floor; landing here is LOSS
  p   plain         — walkable
  s   start         — walkable; the block's initial position
  e   end           — the target hole; WIN by landing UPRIGHT here
  w   weak          — walkable while lying flat; LOSS if the FULL block lands UPRIGHT on it
  W   weak switch   — activates on any contact (upright, lying flat, or a split half)
  S   strong switch — activates only when the FULL block is UPRIGHT on it
  t   teleport      — when the FULL block lands UPRIGHT, instantly moves it to linked position(s)
  B   block marker  — your block's current cell(s); shown on the board for reference only
  A   active half   — active split half; shown on the board in split mode only
  I   inactive half — inactive split half; shown on the board in split mode only
</tile_types>

<bridge_tiles>
Some tiles carry a numbered suffix (e.g. x1, p2, S1, W3). These are "bridge
tiles" whose walkability can be toggled by switches.

  p-type groups (p1, p2, ...) start OPEN  (walkable).
  x-type groups (x1, x2, ...) start CLOSED (missing — LOSS to land on).

The current open/closed state of every group is listed in <toggle_states> in
each turn's user message. A closed bridge tile is treated as missing.
</bridge_tiles>

<orientations>
A normal block always occupies one or two cells.

  UPRIGHT  — occupies 1 cell: (r, c)
  LYING_V  — occupies 2 cells along a column: (r, c) and (r+1, c)
  LYING_H  — occupies 2 cells along a row:    (r, c) and (r, c+1)

UPRIGHT is the only orientation that can:
  * WIN (land on the end tile)
  * trigger a strong switch (S)
  * break a weak tile (w)
  * be teleported by a teleport tile (t)
</orientations>

<block_physics>
The block tips in the move direction. New position by current orientation:

UPRIGHT at (r, c):
  u -> LYING_V : (r-2, c) and (r-1, c)
  d -> LYING_V : (r+1, c) and (r+2, c)
  l -> LYING_H : (r, c-2) and (r, c-1)
  r -> LYING_H : (r, c+1) and (r, c+2)

LYING_V at (r, c) and (r+1, c):
  u -> UPRIGHT : (r-1, c)
  d -> UPRIGHT : (r+2, c)
  l -> LYING_V : (r, c-1) and (r+1, c-1)
  r -> LYING_V : (r, c+1) and (r+1, c+1)

LYING_H at (r, c) and (r, c+1):
  u -> LYING_H : (r-1, c) and (r-1, c+1)
  d -> LYING_H : (r+1, c) and (r+1, c+1)
  l -> UPRIGHT : (r, c-1)
  r -> UPRIGHT : (r, c+2)
</block_physics>

<win_loss_conditions>
WIN  — the block is UPRIGHT and its single occupied cell equals the end tile (e).

LOSS — any of the following after the move resolves:
  * any occupied cell is off the board
  * any occupied cell is missing (x)
  * any occupied cell is a closed bridge tile
  * the FULL block lands UPRIGHT on a weak tile (w)

Lying flat (LYING_V or LYING_H) on a weak tile does NOT cause LOSS.
</win_loss_conditions>

<dead_states>
A DEAD state is distinct from a LOSS:

  LOSS — the last move placed the block on an invalid cell (off the board,
         missing tile, closed bridge, or upright on a weak tile).  The move
         itself was illegal.  A different move from the same position would
         have been fine.

  DEAD — the last move was completely legal; the block is on a valid cell.
         However, exhaustive analysis proves that no sequence of moves from
         this position can ever reach WIN.  The game is unwinnable.  The
         typical cause is activating switches in the wrong order, permanently
         closing a bridge that is required to reach the end tile, with no way
         to reopen it.

When <previous_attempts> shows [DEAD], the critical error was NOT the final
move — it was an earlier move in that attempt, the one that activated the
wrong switch or closed the wrong bridge.  Identify that earlier branch point
and plan a different order of switch activations.
</dead_states>

<special_tile_rules>

<switches>
When a switch is activated, it applies its configured effect to each linked
bridge group:
  "open"   -> group becomes walkable (open)
  "close"  -> group becomes missing  (closed)
  "toggle" -> group flips its current state

The block remains on the switch tile after activation. The move resolves as OK.

Strong switch (S): activated only when the FULL block is UPRIGHT on it.
  A split half landing on S does NOT activate it.

Weak switch (W): activated on any contact — upright, lying flat, or a split half.
</switches>

<teleports>
When the FULL block lands UPRIGHT on a teleport tile (t):
  1-target teleport -> block is instantly moved to that position (stays UPRIGHT, normal mode).
  2-target teleport -> block splits into two halves; see <split_block_rules>.

In both cases the move resolves as OK after the teleport.
</teleports>

<weak_tiles>
A weak tile (w) breaks — and causes LOSS — only when the FULL block lands
UPRIGHT (end-on) on it.

Lying flat on a weak tile (w) is safe and does NOT cause LOSS.
In split mode, a half landing on a weak tile does NOT cause LOSS and does
NOT break the tile.
</weak_tiles>

</special_tile_rules>

<split_block_rules>
Split mode begins when the FULL block lands UPRIGHT on a 2-target teleport tile.
The block splits into two independent halves, one placed at each landing position.

In split mode the board labels each half:
  A — active half   (you control this one this turn)
  I — inactive half (stationary until you switch)

Each half occupies exactly 1 cell. Movement rules:
  u / d / l / r — move the active half one step in that direction
  s             — switch which half is active (no position change)

Do NOT output "s" outside of split mode.

<split_loss_conditions>
LOSS in split mode when the active half moves:
  * off the board
  * onto a missing cell (x)
  * onto a closed bridge tile

Note: a split half landing on a weak tile (w) is safe — it does NOT cause LOSS
and does NOT break the tile.
</split_loss_conditions>

<merge_rules>
The halves merge back into a single block when the active half moves to a cell
that is adjacent to or the same as the inactive half's cell.

  Same cell        (active moves onto inactive's cell)   -> UPRIGHT block
  Adjacent column  (same row, column distance = 1)       -> LYING_H block
  Adjacent row     (same col, row distance = 1)          -> LYING_V block

After merging, normal block physics and WIN/LOSS conditions apply immediately.
WIN is only possible after merging and only when the merged block is UPRIGHT
on the end tile.

If the merge produces a LYING block, additional moves are required to become
UPRIGHT before a WIN is possible.
</merge_rules>

</split_block_rules>

<decision_rules>
1. Never repeat a full move sequence that already ended in LOSS — check
   <previous_attempts> before choosing.
2. Factor in switch effects: activating a switch changes bridge states for
   all subsequent moves in this attempt.
3. In split mode, WIN requires merging first. Both halves must reach positions
   where a merge can produce an UPRIGHT block on or near the end tile.
4. When multiple candidate moves are equally viable, prefer the one that moves
   the block (or active half) closer to the end tile.
5. In split mode, "s" costs a move but changes nothing except which half is
   active — use it only when it enables a better path.
</decision_rules>

<planning_strategy>
Approach the puzzle like a human expert:

1. Target state first: to WIN you need UPRIGHT at the end tile (e).  Before
   planning forward, use <block_physics> in reverse to identify every
   (position, orientation) that reaches WIN in exactly one move — those are
   your immediate pre-WIN targets.

2. Work backward when stuck: pick a pre-WIN target and ask what position reaches
   it in one move.  Repeat 2-3 levels back to build a chain of waypoints, then
   plan a forward path that hits them in order.

3. Switch-first planning: if <toggle_states> shows any bridge groups, decide
   which switches to activate and in what order BEFORE routing.  A path
   through a closed bridge is invalid no matter how short it looks.

4. Learn from state transitions: when <previous_attempts> lists (move -> state)
   pairs, identify the exact step where the state entered a dead end — not just
   the final LOSS position.  Reason about what a different move at that step
   would produce, and whether that new state leads toward a WIN path.
</planning_strategy>

"""

# Turn-by-turn output instructions (one move per API call)
_TURN_INSTRUCTIONS_TURN = """
<turn_instructions>
Each turn, follow these steps:

1. Read <block_state> to confirm whether you are in normal mode or split mode.
2. Normal mode: apply <block_physics> to enumerate where each of u/d/l/r lands
   the block. Split mode: each of u/d/l/r moves the active half one step; "s"
   switches the active half.
3. Eliminate every candidate move that results in LOSS per <win_loss_conditions>
   or <split_loss_conditions>.
4. For surviving candidates, check whether any activates a switch — if so,
   factor the resulting bridge state change into your plan.
5. Check <previous_attempts>: eliminate any candidate that would exactly repeat
   a move sequence that already ended in LOSS.
6. From the remaining candidates, choose the one that best advances toward the
   end tile (e) per <decision_rules>.
7. Output your chosen direction as a SINGLE character on a line by itself.
   Valid output characters: u  d  l  r  (and s in split mode only).
   Output NOTHING else — no explanation, no label, no punctuation.
</turn_instructions>"""

# One-shot output instructions (full attempt sequence in one API call)
_TURN_INSTRUCTIONS_ONE_SHOT = """
<turn_instructions>
You receive the INITIAL board state.  If previous attempts exist, you also
receive every move from each attempt paired with the resulting game state,
exactly as you would observe them turn-by-turn.

Output the COMPLETE move sequence for this attempt as a single space-separated
line.  Apply <block_physics> and <win_loss_conditions> mentally for each step.

Output format: a single line of space-separated direction characters.
Valid characters: u  d  l  r  (and s in split mode only).
Example: r d r r d d r

Output NOTHING else — no explanation, no label, no punctuation.
</turn_instructions>"""

# Final combined prompts
_SYSTEM_PROMPT          = _SYSTEM_PROMPT_BODY + _TURN_INSTRUCTIONS_TURN
_SYSTEM_PROMPT_ONE_SHOT = _SYSTEM_PROMPT_BODY + _TURN_INSTRUCTIONS_ONE_SHOT

# ---------------------------------------------------------------------------
# Model gateway client
# ---------------------------------------------------------------------------

def _call_mgw(
    messages: list[dict],
    model_id: str,
    reasoning_effort: str,
    temperature: float = 0.0,
) -> tuple[str, int, int]:
    """
    Call the model gateway via grpcurl.
    messages  — full conversation: [system, user, assistant, user, ...]
    Returns (content, prompt_tokens, completion_tokens).
    """
    api_key = os.environ.get("MODEL_GATEWAY_API_KEY", "")
    if not api_key:
        raise EnvironmentError("MODEL_GATEWAY_API_KEY is not set")

    is_claude     = "claude" in model_id.lower()
    use_reasoning = reasoning_effort != "none"

    _EFFORT_MAP = {
        "low":    "REASONING_EFFORT_LOW",
        "medium": "REASONING_EFFORT_MEDIUM",
        "high":   "REASONING_EFFORT_HIGH",
    }
    reasoning_effort_proto = _EFFORT_MAP.get(reasoning_effort)

    if is_claude and use_reasoning:
        # Claude extended thinking: temperature must be exactly 1.0;
        # seed and topP are forbidden when thinking is enabled.
        generation_args: dict = {"temperature": 1.0, "reasoningEffort": reasoning_effort_proto}
    elif is_claude:
        # Claude without thinking: disable reasoning explicitly.
        generation_args = {"temperature": temperature, "seed": 42, "topP": 1.0, "reasoning": False}
    elif use_reasoning:
        # OpenAI / other model with reasoning effort.
        generation_args = {"temperature": temperature, "seed": 42, "topP": 1.0, "reasoningEffort": reasoning_effort_proto}
    else:
        # OpenAI / other model, no reasoning.
        generation_args = {"temperature": temperature, "seed": 42, "topP": 1.0}

    payload = json.dumps({
        "model": model_id,
        "messages": messages,
        "generationArgs": generation_args,
    })

    result = subprocess.run(
        [
            "grpcurl",
            "-connect-timeout", "30",
            "-H", f"api_key: {api_key}",
            "-H", f"x-request-id: {uuid.uuid4().hex}",
            "-H", "x-source-app: bloxorz_agent",
            "-import-path", _PROTO_DIR,
            "-proto", "service.proto",
            "-d", payload,
            _MGW_HOST,
            "cicero.protos.model_gateway.v1.ModelGatewayService/ChatCompletion",
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    resp    = json.loads(result.stdout)
    # Claude with extended thinking may return message.content = null when
    # only thinking blocks are present; guard with .get(...) or "".
    message = resp.get("choices", [{}])[0].get("message", {})
    content = message.get("content") or ""
    usage   = resp.get("usage", {})
    prompt_tokens     = int(usage.get("promptTokens", 0))
    completion_tokens = int(usage.get("completionTokens", 0))
    return content, prompt_tokens, completion_tokens


# ---------------------------------------------------------------------------
# State formatter — used inside user-message construction
# ---------------------------------------------------------------------------

def _fmt_state(state) -> str:
    """One-line description of a GameState (duck-typed to avoid circular import)."""
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
# Return types for the two agent modes
# ---------------------------------------------------------------------------

@dataclass
class AttemptPlan:
    """Returned by get_attempt_plan (one-shot mode): full planned move sequence
    for one attempt plus all observability metadata from the single API call."""
    directions: list[Direction]
    user_message: str
    raw_response: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


@dataclass
class MoveDecision:
    direction: Direction
    user_message: str    # full user message sent to the model
    raw_response: str    # raw text received from the model
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def get_next_move(
    session: SessionContext,
    current_state: GameState,
    *,
    model_id: str = _DEFAULT_MODEL,
    reasoning_effort: str = _DEFAULT_REASONING_EFFORT,
    temperature: float = _DEFAULT_TEMPERATURE,
) -> MoveDecision:
    """
    Multi-turn: on the first call of an attempt, initialise the conversation
    with the system prompt.  Every call appends the user message, calls the
    gateway with the full history, then appends the assistant reply.
    session.conversation_history must be reset to [] before each new attempt.

    Prefix-caching note: OpenAI models cache identical prefixes automatically
    (>=1024 tokens, 90% discount).  The system prompt alone (~2500 tokens)
    qualifies, so turns 2+ pay only for the incremental user message.
    """
    is_first_turn = len(session.conversation_history) == 0

    # System prompt is prepended once per attempt (first turn only)
    if is_first_turn:
        session.conversation_history.append({"role": "system", "content": _SYSTEM_PROMPT})

    user_message = _build_user_message(session, current_state, is_first_turn=is_first_turn)
    session.conversation_history.append({"role": "user", "content": user_message})

    t0 = time.monotonic()
    raw, prompt_tokens, completion_tokens = _call_mgw(
        session.conversation_history, model_id, reasoning_effort, temperature
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Append assistant reply so the next turn sees the full history
    session.conversation_history.append({"role": "assistant", "content": raw})

    # Model is instructed to output ONLY the direction character.
    # Scan lines defensively for models that emit reasoning before the answer.
    valid = {d.value for d in Direction}
    for line in raw.strip().splitlines():
        token = line.strip().lower()
        if token in valid:
            return MoveDecision(
                direction=Direction(token),
                user_message=user_message,
                raw_response=raw,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                latency_ms=latency_ms,
            )

    raise RuntimeError(f"No valid direction found in model response: {raw!r}")


# ---------------------------------------------------------------------------
# One-shot mode: plan the full attempt in a single API call
# ---------------------------------------------------------------------------

def get_attempt_plan(
    session: SessionContext,
    current_state: GameState,
    *,
    model_id: str = _DEFAULT_MODEL,
    reasoning_effort: str = _DEFAULT_REASONING_EFFORT,
    temperature: float = _DEFAULT_TEMPERATURE,
) -> AttemptPlan:
    """
    One API call per attempt.  The model receives the full initial board state
    and outputs a space-separated sequence of moves for the entire attempt.
    The caller executes the sequence move-by-move and stops on WIN or LOSS.
    No conversation history — each attempt is a fresh single-turn call.
    """
    user_message = _build_user_message(session, current_state, is_first_turn=True)
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT_ONE_SHOT},
        {"role": "user",   "content": user_message},
    ]

    t0 = time.monotonic()
    raw, prompt_tokens, completion_tokens = _call_mgw(
        messages, model_id, reasoning_effort, temperature
    )
    latency_ms = int((time.monotonic() - t0) * 1000)

    # Parse the sequence robustly.  The model may:
    #  (a) emit reasoning text on earlier lines before the sequence line,
    #  (b) append an invalid token at the very end (e.g. "uu" as a typo).
    # Strategy: take the valid PREFIX of each line, keep the longest one found.
    valid = {d.value for d in Direction}
    best: list[Direction] = []
    for line in raw.strip().splitlines():
        prefix: list[Direction] = []
        for tok in line.strip().lower().split():
            if tok in valid:
                prefix.append(Direction(tok))
            else:
                break   # stop at first invalid token on this line
        if len(prefix) > len(best):
            best = prefix
    directions = best

    if not directions:
        raise RuntimeError(f"No valid move sequence in one-shot response: {raw!r}")

    return AttemptPlan(
        directions=directions,
        user_message=user_message,
        raw_response=raw,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# User message — all dynamic, per-turn data goes here
# ---------------------------------------------------------------------------

def _build_user_message(
    session: SessionContext,
    current_state: GameState,
    *,
    is_first_turn: bool,
) -> str:
    """
    Build the user message for the current turn.

    is_first_turn=True  (turn 1 of an attempt):
      Includes <current_attempt> and <previous_attempts> so the model has
      full context at the start of each new attempt.

    is_first_turn=False (turns 2+ of the same attempt):
      Omits both sections — the model already has that context in the
      conversation history, so repeating it wastes tokens.
    """
    level = session.level
    parts: list[str] = []

    # 1. Board — trimmed rows; reflects toggle states, broken tiles, block pos
    parts.append(f"<board>\n{_render_board(level, current_state)}\n</board>")

    # 2. Block state
    if current_state.split is not None:
        sp = current_state.split
        a_pos = sp.half1 if sp.active == 0 else sp.half2
        i_pos = sp.half2 if sp.active == 0 else sp.half1
        parts.append(
            f"<block_state>\n"
            f"  mode: SPLIT\n"
            f"  active half (A): ({a_pos[0]}, {a_pos[1]})\n"
            f"  inactive half (I): ({i_pos[0]}, {i_pos[1]})\n"
            f"</block_state>"
        )
    else:
        b = current_state.block
        if b.orientation == Orientation.UPRIGHT:
            pos_str = f"({b.pos1[0]}, {b.pos1[1]})"
        else:
            pos_str = f"({b.pos1[0]}, {b.pos1[1]}) -- ({b.pos2[0]}, {b.pos2[1]})"
        parts.append(
            f"<block_state>\n"
            f"  mode: NORMAL\n"
            f"  orientation: {b.orientation.value}\n"
            f"  position: {pos_str}\n"
            f"</block_state>"
        )

    # 3. Goal — always included; short and keeps model anchored
    parts.append(
        f"<goal>end tile (e) is at ({level.end_pos[0]}, {level.end_pos[1]})</goal>"
    )

    # 4. Toggle states — only when the level has bridge groups
    if level.group_initial_open:
        lines = []
        for gid, initial_open in sorted(level.group_initial_open.items()):
            current_open = current_state.toggle_states.get(gid, initial_open)
            lines.append(f"  {gid}: {'open' if current_open else 'closed'}")
        parts.append("<toggle_states>\n" + "\n".join(lines) + "\n</toggle_states>")

    # 5. Broken weak tiles — only when any exist this attempt
    if current_state.broken_tiles:
        broken = ", ".join(f"({r},{c})" for r, c in sorted(current_state.broken_tiles))
        parts.append(f"<broken_tiles>{broken}</broken_tiles>")

    # 6 & 7. First-turn-only sections:
    #   <current_attempt> — move history the model has already seen in the
    #     conversation is redundant on turns 2+; saves ~30-100 tokens/turn.
    #   <previous_attempts> — only relevant at attempt start; model already
    #     saw it in the first user message of this attempt.
    if is_first_turn:
        # Cross-level context (sequence mode only)
        if session.level_history:
            hist_lines: list[str] = []
            for lh in session.level_history:
                hist_lines.append(f"  {lh['level_id']} [{lh['result']}]:")
                for att in lh["attempts"]:
                    seq = " ".join(att["moves"])
                    hist_lines.append(
                        f"    attempt {att['attempt_num']} "
                        f"[{att['status']}, {len(att['moves'])} moves]: {seq}"
                    )
            parts.append(
                "<level_history>\n" + "\n".join(hist_lines) + "\n</level_history>"
            )

        attempt = session.current_attempt
        moves_str = (
            " ".join(m.direction.value for m in attempt.history)
            if attempt.history else "(none yet)"
        )
        parts.append(
            f"<current_attempt>\n"
            f"  attempt: {attempt.attempt_num}\n"
            f"  moves so far ({len(attempt.history)}): {moves_str}\n"
            f"</current_attempt>"
        )

        # Previous completed attempts — each move paired with its resulting state,
        # matching the information density the model gets turn-by-turn.
        # Toggle state changes are shown inline when they occur.
        if session.completed_attempts:
            all_lines: list[str] = []
            for prev in session.completed_attempts:
                outcome = "DEAD" if prev.dead else prev.status.value
                all_lines.append(
                    f"  attempt {prev.attempt_num} "
                    f"[{outcome} after {len(prev.history)} moves]:"
                )
                # Track bridge toggle state through the attempt so we can
                # show diffs; start from the level's initial open/closed state.
                prev_toggle: dict[str, bool] = {}

                for idx, move in enumerate(prev.history):
                    res          = move.resulting_state
                    is_terminal  = idx == len(prev.history) - 1
                    state_str    = _fmt_state(res)

                    # Detect bridge toggle changes caused by this move
                    toggle_diffs: list[str] = []
                    for gid, new_open in res.toggle_states.items():
                        old_open = prev_toggle.get(
                            gid, level.group_initial_open.get(gid, True)
                        )
                        if old_open != new_open:
                            toggle_diffs.append(
                                f"{gid}: {'open' if old_open else 'closed'}"
                                f"->{'open' if new_open else 'closed'}"
                            )
                    prev_toggle = dict(res.toggle_states)

                    toggle_str  = f"  (bridges: {', '.join(toggle_diffs)})" if toggle_diffs else ""
                    terminal_tag = ("DEAD" if prev.dead else prev.status.value) if is_terminal else ""
                    status_str   = f"  [{terminal_tag}]" if terminal_tag else ""

                    all_lines.append(
                        f"    {idx + 1}: {move.direction.value}  ->  "
                        f"{state_str}{toggle_str}{status_str}"
                    )
            parts.append(
                "<previous_attempts>\n" + "\n".join(all_lines) + "\n</previous_attempts>"
            )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Board renderer
# ---------------------------------------------------------------------------

def _render_board(level, current_state: GameState) -> str:
    board = [["x"] * level.cols for _ in range(level.rows)]

    for (r, c), tile in level.grid.items():
        if (r, c) in current_state.broken_tiles:
            continue  # broken weak tile -> stays 'x'

        if tile.group_id is not None:
            initial_open = level.group_initial_open.get(tile.group_id, True)
            is_open = current_state.toggle_states.get(tile.group_id, initial_open)
            if is_open:
                # x-type bridge that is now open renders as plain walkable
                char = "p" if tile.tile_type == TileType.MISSING else tile.tile_type.value
                board[r][c] = char
            # else: closed bridge -> stays 'x'
        else:
            board[r][c] = tile.tile_type.value

    if current_state.split is not None:
        sp = current_state.split
        active_pos   = sp.half1 if sp.active == 0 else sp.half2
        inactive_pos = sp.half2 if sp.active == 0 else sp.half1
        r, c = active_pos
        if 0 <= r < level.rows and 0 <= c < level.cols:
            board[r][c] = "A"
        r, c = inactive_pos
        if 0 <= r < level.rows and 0 <= c < level.cols:
            board[r][c] = "I"
    else:
        for r, c in current_state.block.occupied:
            if 0 <= r < level.rows and 0 <= c < level.cols:
                board[r][c] = "B"

    # Trim trailing missing ('x') cells from each row to cut token count.
    # The model infers board width from block/goal coordinates; trailing
    # absent floor cells carry no information.
    rows_out = []
    for row in board:
        last = len(row)
        while last > 1 and row[last - 1] == "x":
            last -= 1
        rows_out.append(" ".join(row[:last]))
    return "\n".join(rows_out)

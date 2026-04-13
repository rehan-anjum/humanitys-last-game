#!/usr/bin/env bash
# mgw_call.sh — call the model gateway like curl.
#
# Self-contained: no repo, no proto files, no Python env needed.
#
# Dependencies (one-time):
#   brew install grpcurl jq
#   export MODEL_GATEWAY_API_KEY=sk-...
#
# Usage:
#   ./mgw_call.sh --user "What is 2+2?"
#   ./mgw_call.sh --user "Summarize this" --system "Be concise" --model oai-gpt-4.1-2025-04-14
#   ./mgw_call.sh --user "Complex task" --temperature 0 --reasoning-effort high
#   ./mgw_call.sh --user "Hello" --reasoning-effort none --temperature 0.7

set -euo pipefail

HOST="staging.model-gateway.us-west-2.cicerotech.link:443"

# Write the minimal proto inline to a temp dir — no repo required.
# Stripped to only what ChatCompletion needs; google/protobuf/struct.proto
# import is not needed once tools/ResponseFormat are removed.
PROTO_DIR=$(mktemp -d)
trap 'rm -rf "$PROTO_DIR"' EXIT

cat > "$PROTO_DIR/service.proto" << 'PROTO'
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
  optional int32 seed                   = 1;
  optional float temperature            = 2;
  optional int32 max_completion_tokens  = 3;
  optional float top_p                  = 4;
  optional bool  reasoning              = 12;
  oneof reasoning_config {
    ReasoningEffort reasoning_effort    = 13;
    int32           thinking_budget_tokens = 14;
  }
}

message Message {
  string          role    = 1;
  optional string content = 2;
}

message ChatCompletionRequest {
  string                    model           = 1;
  repeated Message          messages        = 2;
  optional GenerationArgs   generation_args = 3;
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
PROTO

PROTO_IMPORT_PATH="$PROTO_DIR"
PROTO_FILE="service.proto"

# Defaults
MODEL="oai-gpt-5-2-2025-12-11"
USER_PROMPT=""
SYSTEM_PROMPT=""
TEMPERATURE=0.0
REASONING_EFFORT="REASONING_EFFORT_HIGH"
DISABLE_REASONING=false
MAX_TOKENS=""

usage() {
  cat <<EOF
Usage: $(basename "$0") --user PROMPT [options]

Options:
  --user TEXT              User message/prompt (required)
  --system TEXT            System message/prompt
  --model ID               Model ID (default: $MODEL)
  --temperature N          Sampling temperature 0.0–2.0 (default: 0.0)
  --reasoning-effort LEVEL none | low | medium | high (default: high)
  --max-tokens N           Max completion tokens
  -h, --help               Show this help

Environment:
  MODEL_GATEWAY_API_KEY    Required. API key for the model gateway.

Examples:
  export MODEL_GATEWAY_API_KEY=sk-...
  $(basename "$0") --user "What is the capital of France?"
  $(basename "$0") --model oai-gpt-4.1-2025-04-14 --user "Classify this risk" --system "Legal assistant"
  $(basename "$0") --user "Translate to Spanish" --reasoning-effort none --temperature 0.3
EOF
  exit 1
}

# Parse args
while [[ $# -gt 0 ]]; do
  case "$1" in
    --user)              USER_PROMPT="$2";  shift 2 ;;
    --system)            SYSTEM_PROMPT="$2"; shift 2 ;;
    --model)             MODEL="$2";        shift 2 ;;
    --temperature)       TEMPERATURE="$2";  shift 2 ;;
    --max-tokens)        MAX_TOKENS="$2";   shift 2 ;;
    --reasoning-effort)
      case "$2" in
        none)   DISABLE_REASONING=true; REASONING_EFFORT="" ;;
        low)    REASONING_EFFORT="REASONING_EFFORT_LOW"    ;;
        medium) REASONING_EFFORT="REASONING_EFFORT_MEDIUM" ;;
        high)   REASONING_EFFORT="REASONING_EFFORT_HIGH"   ;;
        *)      echo "Error: --reasoning-effort must be none|low|medium|high"; exit 1 ;;
      esac
      shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown flag: $1"; usage ;;
  esac
done

[[ -z "$USER_PROMPT" ]] && { echo "Error: --user is required"; echo; usage; }
[[ -z "${MODEL_GATEWAY_API_KEY:-}" ]] && { echo "Error: MODEL_GATEWAY_API_KEY is not set"; exit 1; }

# Build messages array
if [[ -n "$SYSTEM_PROMPT" ]]; then
  MESSAGES=$(jq -n --arg sys "$SYSTEM_PROMPT" --arg usr "$USER_PROMPT" \
    '[{"role":"system","content":$sys},{"role":"user","content":$usr}]')
else
  MESSAGES=$(jq -n --arg usr "$USER_PROMPT" '[{"role":"user","content":$usr}]')
fi

# Claude's extended thinking API requires temperature=1.0 and forbids top_p/seed.
# Auto-detect Claude models and adjust accordingly.
IS_CLAUDE=false
[[ "$MODEL" == *claude* ]] && IS_CLAUDE=true

if [[ "$IS_CLAUDE" == true && "$DISABLE_REASONING" == false ]]; then
  # Extended thinking: temperature must be 1.0; top_p and seed must be omitted.
  GEN_ARGS=$(jq -n '{"temperature": 1.0}')
else
  GEN_ARGS=$(jq -n --argjson temp "$TEMPERATURE" '{"temperature":$temp,"seed":42,"topP":1.0}')
fi

if [[ "$DISABLE_REASONING" == true ]]; then
  GEN_ARGS=$(echo "$GEN_ARGS" | jq '. + {"reasoning": false}')
else
  GEN_ARGS=$(echo "$GEN_ARGS" | jq --arg re "$REASONING_EFFORT" '. + {"reasoningEffort":$re}')
fi

if [[ -n "$MAX_TOKENS" ]]; then
  GEN_ARGS=$(echo "$GEN_ARGS" | jq --argjson mt "$MAX_TOKENS" '. + {"maxCompletionTokens":$mt}')
fi

PAYLOAD=$(jq -n \
  --arg     model    "$MODEL"    \
  --argjson messages "$MESSAGES" \
  --argjson gen_args "$GEN_ARGS" \
  '{"model":$model,"messages":$messages,"generationArgs":$gen_args}')

# Call grpcurl and extract the response text
grpcurl \
  -connect-timeout 10 \
  -H "api_key: ${MODEL_GATEWAY_API_KEY}" \
  -H "x-request-id: $(uuidgen | tr '[:upper:]' '[:lower:]')" \
  -H "x-source-app: mgw_call" \
  -import-path "$PROTO_IMPORT_PATH" \
  -proto "$PROTO_FILE" \
  -d "$PAYLOAD" \
  "$HOST" \
  "cicero.protos.model_gateway.v1.ModelGatewayService/ChatCompletion" \
  | jq -r '.choices[0].message.content'

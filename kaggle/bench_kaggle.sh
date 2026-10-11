#!/usr/bin/env bash
# Benchmark the assistant on a Kaggle notebook with 2 GPUs (e.g. "GPU T4 x2"), no Docker.
# Everything runs as plain processes: Postgres, Redis, Qdrant, vLLM (tensor parallel over both
# GPUs) and the API. Internet must be ON in the notebook settings.
#
#   bash kaggle/bench_kaggle.sh            # full run, ~25-40 min, mostly installs + model download
#   RUNS=20 bash kaggle/bench_kaggle.sh    # more timed runs per scenario
#
# NOT TESTED by the author on a real Kaggle session (no GPU available when it was written).
# Expect to fix a version pin or two. Every step is idempotent, so just re-run after fixing.
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
W=${WORK:-/kaggle/working}; mkdir -p "$W"
MODEL=${VLLM_MODEL:-Qwen/Qwen2.5-7B-Instruct}
GPUS=${VLLM_GPUS:-2}
RUNS=${RUNS:-10}
VLLM_VERSION=${VLLM_VERSION:-0.9.2}
QDRANT_VERSION=${QDRANT_VERSION:-v1.13.6}
TRANSFORMERS_VERSION=${TRANSFORMERS_VERSION:-4.53.3}
export VLLM_API_KEY=${VLLM_API_KEY:-bench-key}

step() { echo; echo "=== $* ==="; }
# wait_http URL NAME TRIES [PID]: poll every 5 s; give up early if PID (the server) has died.
wait_http() {
  for _ in $(seq 1 "${3:-120}"); do
    curl -fsS "$1" >/dev/null 2>&1 && return 0
    if [ -n "${4:-}" ] && ! kill -0 "$4" 2>/dev/null; then echo "$2 process exited" >&2; return 1; fi
    sleep 5
  done
  echo "timeout waiting for $2" >&2; return 1
}

step "GPUs"
nvidia-smi --query-gpu=name,memory.total --format=csv
[ "$(nvidia-smi -L | wc -l)" -ge "$GPUS" ] || { echo "need $GPUS GPUs (pick 'GPU T4 x2' in notebook settings)"; exit 1; }

step "System services (Postgres, Redis, Qdrant)"
if ! command -v psql >/dev/null; then apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql redis-server >/dev/null; fi
service postgresql start >/dev/null
su postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='telecom'\" | grep -q 1 || psql -c \"CREATE USER telecom WITH PASSWORD 'telecom' SUPERUSER\""
su postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='telecom'\" | grep -q 1 || createdb -O telecom telecom"
# No TimescaleDB here: provide a no-op create_hypertable so the unchanged migrations apply.
# Only affects storage layout, not what is benchmarked.
PGPASSWORD=telecom psql -h localhost -U telecom telecom -q -c \
 "CREATE OR REPLACE FUNCTION create_hypertable(regclass, name, if_not_exists boolean DEFAULT false) RETURNS void LANGUAGE sql AS 'SELECT 1'"
(redis-cli ping >/dev/null 2>&1) || (redis-server --daemonize yes >/dev/null)
if [ ! -x "$W/qdrant" ]; then
  curl -fsSL "https://github.com/qdrant/qdrant/releases/download/${QDRANT_VERSION}/qdrant-x86_64-unknown-linux-gnu.tar.gz" | tar -xz -C "$W"
fi
if ! curl -fsS localhost:6333/healthz >/dev/null 2>&1; then
  (cd "$W" && nohup ./qdrant > qdrant.log 2>&1 &)
fi
wait_http localhost:6333/healthz qdrant 24

step "Python environments (uv: Debian's python3-venv/ensurepip is missing on Kaggle)"
pip install -q uv
PYV=${PYTHON_VERSION:-3.12}   # Kaggle runs Python 3.13; vLLM 0.9.x has no 3.13 wheels (outlines-core needs Rust)
[ -x "$W/app-env/bin/python" ] || uv venv -q --python "$PYV" "$W/app-env"
# Separate env: installing into Kaggle's own Python caused dependency conflicts with its preinstalled libs.
uv pip install -q --python "$W/app-env/bin/python" -r requirements.txt
PY="$W/app-env/bin/python"

step "vLLM ${VLLM_VERSION} in its own venv (keeps Kaggle's torch untouched)"
if [ ! -x "$W/vllm-env/bin/vllm" ]; then
  rm -rf "$W/vllm-env"
  uv venv -q --python "$PYV" "$W/vllm-env"
  # transformers>=4.54 registers "aimv2" itself and vLLM 0.9.x then crashes on import ("already used"), so pin below it.
  uv pip install -q --python "$W/vllm-env/bin/python" "vllm==${VLLM_VERSION}" "transformers==${TRANSFORMERS_VERSION}"
fi
# Idempotent: repairs an env created before the pin existed (no-op when already pinned).
uv pip install -q --python "$W/vllm-env/bin/python" "transformers==${TRANSFORMERS_VERSION}"
if ! curl -fsS localhost:8000/health >/dev/null 2>&1; then
  # T4 = compute 7.5: no bf16, V1 engine unsupported -> half precision + V0 + xformers.
  VLLM_USE_V1=0 VLLM_ATTENTION_BACKEND=XFORMERS nohup "$W/vllm-env/bin/vllm" serve "$MODEL" \
    --served-model-name "$MODEL" --api-key "$VLLM_API_KEY" --dtype half \
    --tensor-parallel-size "$GPUS" --max-model-len 8192 --gpu-memory-utilization 0.88 \
    --enable-auto-tool-choice --tool-call-parser hermes --disable-custom-all-reduce \
    > "$W/vllm.log" 2>&1 &
  VLLM_PID=$!
fi
echo "waiting for vLLM to download and load $MODEL (first run: several minutes)"
wait_http localhost:8000/health vllm 240 "${VLLM_PID:-}" || { tail -40 "$W/vllm.log"; exit 1; }

step "Assistant environment"
export DATABASE_URL=postgresql://telecom:telecom@localhost:5432/telecom
export QDRANT_URL=http://localhost:6333 REDIS_URL=redis://localhost:6379/0
export VLLM_BASE_URL=http://localhost:8000/v1
export LLM_MODEL="hosted_vllm/$MODEL" JUDGE_MODEL="hosted_vllm/$MODEL" GUARD_MODEL="hosted_vllm/$MODEL"
export LLM_FALLBACK_MODEL="hosted_vllm/$MODEL"   # no Ollama here: a fallback must not hide a vLLM failure
export AUTH_REQUIRED=0 RATE_LIMIT_PER_MIN=100000 IP_RATE_LIMIT_PER_MIN=100000
export AGENT_MODE=agentic TOOLS_VIA_MCP=1 LOG_JSON=0
"$PY" -m scripts.migrate
"$PY" -m scripts.ingest
"$PY" -m scripts.seed_kpis

step "Start API"
pkill -f "uvicorn app.main" 2>/dev/null || true
# Wait for the old API (from an earlier run) to release the port; otherwise /health below can be
# answered by the dying old process while the new one fails to bind, and every request is refused.
for _ in $(seq 1 20); do curl -fsS localhost:8001/health >/dev/null 2>&1 || break; sleep 1; done
nohup "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port 8001 > "$W/api.log" 2>&1 &
API_PID=$!
wait_http localhost:8001/health api 36 "$API_PID" || { echo "--- api.log (tail) ---"; tail -60 "$W/api.log"; exit 1; }

step "Benchmark"
GPU_NAMES=$(nvidia-smi --query-gpu=name --format=csv,noheader | sort | uniq -c | tr -s ' ' | paste -sd, -)
"$PY" scripts/bench_incident.py --url http://localhost:8001 --runs "$RUNS" --warmup 2 \
  --label "${GPU_NAMES}; vLLM ${VLLM_VERSION} TP=${GPUS}; ${MODEL}; agentic+MCP" \
  --out "$W/bench_result.json" | tee "$W/bench_output.txt"
step "Agent eval (ground-truth detection, tool use, stability, LLM judge)"
# Judge = the same 7B model here (only one model fits). Treat the judge numbers as indicative.
"$PY" -m evals.run_agent_eval --url http://localhost:8001 --repeats "${EVAL_REPEATS:-3}" --judge \
  --label "${GPU_NAMES}; vLLM ${VLLM_VERSION} TP=${GPUS}; ${MODEL}; agentic+MCP" \
  --out "$W/agent_eval.json" | tee "$W/agent_eval_output.txt"

echo; echo "Results: $W/bench_result.json   Agent eval: $W/agent_eval.json   Logs: $W/vllm.log $W/api.log"

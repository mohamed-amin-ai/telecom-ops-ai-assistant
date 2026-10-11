# Benchmarking on Kaggle (2 GPUs)

Goal: a real, citable number for "alert to drafted diagnosis" time with a real model.

1. Kaggle > New Notebook > upload `kaggle/bench.ipynb` (or paste its cells).
2. Settings: Accelerator **GPU T4 x2**, Internet **On**.
3. Run all cells. First run: 25-40 min (apt packages, vLLM install, 15 GB model download).
4. Read the last cell (or `/kaggle/working/bench_result.json`): median / p95 per scenario and
   how the agent behaved (tool calls per incident, share of calls filled by the safety net).

`kaggle/bench_kaggle.sh` runs everything as plain processes (no Docker on Kaggle): Postgres,
Redis, Qdrant, vLLM with tensor parallelism over both GPUs, then the API. `scripts/bench_incident.py`
does the timing and works against any running API.

**Status: not run on a real Kaggle session** (the author had no GPU access when writing it). Likely
snags: the vLLM version pin vs the CUDA driver on the image, `apt` package availability, and
T4-specific vLLM flags (half precision, V0 engine, xformers). Everything is idempotent, so fix and re-run.

**What the number means.** Timed from request to "awaiting approval" over 3 scenarios x N runs on the
seeded database, on that GPU and model. It excludes the human approval. Quote it as such, with the label
the script writes (GPU, model, tensor-parallel size). Time the manual workflow the same way on the same
incidents before comparing.

Without Timescale, the script installs a no-op `create_hypertable` so migrations apply unchanged.
Also fixed while writing this: `docker-compose.vllm.yml` lacked `--enable-auto-tool-choice` and
`--tool-call-parser`, without which vLLM rejects tool calls and the agent silently fell back to the
fixed pipeline.

To re-run only the agent eval (skips the 30-run latency benchmark; still starts vLLM and the API):
`!SKIP_BENCH=1 bash kaggle/bench_kaggle.sh`

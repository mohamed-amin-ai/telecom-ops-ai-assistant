# Telecom Ops Assistant

[![ci](https://github.com/mohamed-amin-ai/telecom-ops-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/mohamed-amin-ai/telecom-ops-assistant/actions/workflows/ci.yml)
![license](https://img.shields.io/badge/license-MIT-blue)

RAG + agentic assistant for telecom network operations. Alert in, then KPI profile and
runbook retrieval, diagnosis, human approval, ticket, incident report. No AWS dependency.

```mermaid
flowchart LR
  A[Alert or question] --> G[Input guardrails]
  G --> R[Hybrid retrieval<br/>Qdrant dense + BM25]
  G --> K[KPI profile<br/>TimescaleDB]
  R --> D[LLM diagnosis<br/>LiteLLM: Anthropic / Ollama]
  K --> D
  D --> O[Output guardrails]
  O --> H{Human approval}
  H -->|approve| T[Ticket + incident report]
  D -.-> L[Langfuse traces]
```

## Run
```bash
cp .env.example .env                 # set ANTHROPIC_API_KEY
docker compose up -d --build         # add --profile local for Ollama fallback
docker compose exec api python -m scripts.ingest      # index data/docs
docker compose exec api python -m scripts.seed_kpis   # synthetic KPIs with 3 injected faults
```
- Chat UI: http://localhost:8080. Ask a question, or run
  `/incident CELL_001 prb_utilization_pct PRB above 85%` (also try `CELL_002
  rrc_setup_success_rate`, `CELL_003 handover_success_rate`). Approve to create the ticket.
- API docs: http://localhost:8000/docs
- Langfuse: http://localhost:3000. Create a project, paste the keys into `.env`, then
  `docker compose up -d api`.
- Local model: `docker compose exec ollama ollama pull qwen2.5:7b-instruct`.

## Evals
```bash
docker compose exec api python -m evals.run_eval          # retrieval: dense vs hybrid vs hybrid+rerank
docker compose exec api python -m evals.run_gen_eval      # answers: correctness, faithfulness, abstention
docker compose exec api python -m evals.run_guard_eval    # guardrails: injection, privacy, scope, PII
```
`evals/golden_set.jsonl` has 121 questions (110 answerable, 11 unanswerable) written against
the 22 documents in `data/docs/`. `evals/guardrail_set.jsonl` has 38 input cases. Change `RETRIEVAL_MODE` / `RERANK` in `.env`, restart the
api, and re-run `run_gen_eval` to compare configurations. Failures are written to
`evals/last_failures.json`.

## Guardrails
- **Input** (`/ask`): PII redaction (emails, phone numbers, IMSI/IMEI/MSISDN-length IDs),
  deterministic rules for prompt injection and subscriber tracking, then a small LLM
  classifier (`GUARD_MODEL`) that blocks off-topic, injection and harmful requests.
- **Alerts** (`/incident`): the free-text description gets redaction and the rules (no
  LLM call). Cell ID and KPI name are pattern-validated.
- **Output**: PII redaction, and answers with neither a `[source#chunk]` citation nor an
  abstention get an "unverified" note. Retrieved text and alert text are treated as data
  in the prompts.
- **Actions**: tools are read-only; tickets are created only after human approval.
- **API**: optional `X-API-Key` (set `API_KEY`), per-client rate limit, request size limits.
- Switches: `GUARDRAILS=0` disables all; `GUARD_LLM=0` keeps the rules and drops the
  classifier. If the classifier call fails it fails open (rules still apply) and logs.

## Layout
- `app/rag.py`: ingest and hybrid retrieval (Qdrant dense + BM25, RRF, optional rerank)
- `app/agent.py`: LangGraph flow with human approval (`interrupt`)
- `app/tools.py`, `app/stats.py`: KPI query and local same-hour-baseline z-score profile
- `app/mcp_server.py`: read-only tools over MCP (`python -m app.mcp_server`)
- `app/guard_rules.py`, `app/guardrails.py`: input/output guardrails
- `app/llm.py`: LiteLLM entry point (Anthropic primary, Ollama fallback, Langfuse tracing)
- `ui/app.py`: Chainlit UI
- `evals/`: golden set, retrieval ablation, LLM-judge generation eval

## Limits
- The 22 documents are synthetic: operational thresholds and policies are invented, and
  the two concept primers (16, 17) are written from general knowledge, so check them against
  the 3GPP specs before relying on them. Replace them with your own runbooks when you have
  them.
  Scores show the pipeline works and let you compare configurations, but the questions
  overlap the docs closely, so expect high numbers. Add your own documents and harder,
  paraphrased questions before drawing conclusions.
- Guardrails are heuristic. Regex rules miss paraphrased attacks and the LLM classifier can
  err in both directions; grow `guardrail_set.jsonl` with real traffic.
- The agent calls tools directly. The MCP server is for external clients.
- Tickets go to `data/tickets.jsonl`, and agent state is in memory (lost on restart).

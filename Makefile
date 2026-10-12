.PHONY: help up down ingest seed test lint eval-tools
COMPOSE = docker compose -f docker-compose.yml -f docker-compose.dev.yml

help:  ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

up:  ## start the stack (needs a filled-in .env)
	$(COMPOSE) up -d --build

down:  ## stop the stack
	$(COMPOSE) down

ingest:  ## index data/docs into Qdrant
	$(COMPOSE) exec api python -m scripts.ingest

seed:  ## load synthetic KPIs with 3 injected faults
	$(COMPOSE) exec api python -m scripts.seed_kpis

test:  ## unit tests (no services needed)
	pytest -q

lint:  ## ruff
	ruff check .

eval-tools:  ## tool-selection eval on the held-out set (needs a model; MODEL=ollama_chat/qwen2.5:3b-instruct)
	$(COMPOSE) exec api python -m evals.run_tool_eval --set evals/tool_selection_heldout.jsonl --model $(MODEL)

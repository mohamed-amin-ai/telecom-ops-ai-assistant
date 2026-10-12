# Engineering log

Bugs found by running the system end to end and by an independent code review, and what is still not production grade.

## Found and fixed by running it end to end
`docker compose up` had never been run before the `stack` CI job existed, because it was
built and validated with stubbed embeddings and a mocked LLM. Running the real stack found
real bugs, each with a regression test:
- **LiteLLM rejects `temperature=0` for some models.** `app/llm.py` retries once
  without `temperature` on that specific error.
- **The KPI anomaly check missed faults on ratio KPIs near 100%** (noise floor was too wide
  relative to how little those KPIs normally move). Tightened from 5% to 1% of baseline.
- **Headless Chromium's OS locale broke Chainlit's own settings endpoint**, and separately,
  **typing during Chainlit's socket handshake got silently wiped**. Fixed with a forced
  browser locale and a type-verify-retry helper.
- **No `.dockerignore` meant a CI-generated `.env` was baked into every image via
  `COPY . .`**, and Chainlit's own `__init__.py` unconditionally reloads `.env` from its
  working directory on import -- so the UI container picked up the API's `DATABASE_URL`
  and tried to use it as its own (incompatible) chat-persistence database. Also meant
  API keys were leaking into every image layer. A `.dockerignore` fixes both.
- **Hosted gateways preflight-check cost against `max_tokens`** and rate-limit in bursts.
  Capped `max_tokens` by default and added `litellm`'s own retry/backoff for transient rate limits.
- **RAGAS on a local model needed two fixes before it produced a score.** ResponseRelevancy
  asks for several completions per call (`n=3`) and Ollama has no `n`, so litellm raised on
  every such row (fixed by dropping unsupported params in the eval script only). Then every
  relevancy row failed validation because ragas builds a usage event from the embeddings'
  `.model`, which must be a string and was LangChain's loaded model object (fixed with a
  small named-embeddings adapter). Both have regression tests; the second also showed up as
  `nan_rows` of 6/6 in the output instead of passing silently, which is what the NaN check
  added earlier is for.
- **A swallowed primary-provider exception, an oversized traceback, a noisy third-party
  banner, and this project's own `exc_info=True` logging** each independently buried the
  actual error under CI log truncation at different points -- four separate fixes before the
  real provider errors were even visible. The lesson embedded in the code now: guard
  the fail-open logging path against duplicate-request-during-an-outage log floods
  (`app/guardrails.py`), and prefer a short greppable line over `exc_info=True` for anything
  that can fire once per request.

## Independent code audit (found and fixed)
A separate reviewer read the core code and probed it with throwaway scripts. Confirmed defects, all fixed with regression tests:
- **A "reject" retry could still create a ticket.** If the ticket step failed after approval, the checkpoint waited on
  `ticket`; `/decision` only checked that something was pending and ignored the resume value. Now `/decision` resumes only a
  pending `approval`; a retry of a failed later step may repeat the *same* decision (409 otherwise), and `create_ticket` is
  idempotent per incident (existing-row check, plus a unique index in migration 0005).
- **The agent could present another cell's evidence.** Tool arguments were only regex-validated, so a model steered by alert text
  could call `kpi_profile` for `CELL_999` and the approver saw it as this alert's profile. Tools are now pinned to the alerted
  cell (and KPI for `kpi_profile`).
- **A silent cell looked healthy.** The detector compared the last data point with itself, so a feed that stopped 10 h ago
  was "not anomalous". It now reports data older than 2 h as anomalous ("feed stopped or cell silent"). NaN/inf values no longer
  break detection or JSON serialisation.
- **One slow MCP call killed healthy ones.** The wait for the shared pipe counted against a queued caller's timeout and a timeout
  closed the whole session. Queue-wait and run time are now bounded separately, only the failed session generation is closed,
  and event loops are released on restart.
- Smaller: SSO users are namespaced (`sso:<name>`) so they cannot share a rate-limit bucket or audit identity with an API-key
  user; a malformed role claim is a 401 not a 500; `/audit?limit=` is validated; an audit-write failure after a ticket exists no
  longer turns a success into a 500.
- **Known and not fixed:** `/decision` holds one DB connection for the whole graph run, so about `DB_POOL_MAX` concurrent approvals
  can starve the pool (reasoned, not load-tested); the advisory-lock key is a 32-bit hash (rare spurious 409); the detector does not
  scale z by sqrt(n), so a sustained small shift is under-detected; the DB session timezone is assumed fixed (no DST handling).

## Not production grade yet
Real Postgres-backed agent state, real persistence, versioned migrations, per-user auth
with an append-only audit trail, Redis-backed rate limiting, TLS via Caddy, metrics/alerts,
backup-and-restore verification, and a red-teamed (modest) guardrail layer. Still
missing, roughly in order of what would fail first:
- **The webhook and Sentry scrubbing are tested against a local receiver, not a
  real ITSM system or Sentry account** -- the signature/retry/redaction logic is verified,
  the integration with a specific real vendor is not.
- **Grafana SSO is configured but untested.** It sits behind Caddy basic auth plus its own
  login, and the prod overlay has optional OIDC settings (`GRAFANA_OIDC_*`) for Okta/Entra/
  Keycloak/etc.; they could not be tested without an identity provider.
- **No secrets manager** (Vault, cloud KMS): secrets are environment variables, optionally
  sourced from mounted files via `scripts/entrypoint.sh` -- no rotation built in.
- **Load testing is still against a fake LLM and the CI runner.** `scripts/load_test.py`
  now has an open-loop soak mode (`--rps N --duration S`, fixed arrival rate, so slow
  responses show up as queueing instead of being hidden) and CI runs 60 s at 5 req/s, but
  that is one small runner with stubbed model latency -- not production-shaped traffic,
  real model latency, or hours-long soak. Run `--rps` against your own deployment with your
  real model to get numbers that mean something.
- **Deploys restart the API (a few seconds of downtime) and there is one host.**
  `scripts/deploy.sh <tag>` builds a tagged image, runs migrations, starts it, waits for
  `/ready`, and rolls back to the previous tag automatically if it never becomes healthy
  (`--rollback` does it by hand; the control flow is tested against a fake `docker
  compose`, not real containers). Migrations are forward-only: a rollback does not undo a
  schema change, so write migrations that the previous version can still run against.
  No autoscaling, no multi-host, no zero-downtime.
- **Third-party images are pinned** (`QDRANT_TAG`, `TIMESCALE_TAG`, ... in the compose files)
  instead of `:latest`, so a rebuild can't silently change versions; bumping them is now a
  deliberate edit that CI exercises. Langfuse is pinned to its `:2` major only.
- **Only small free local models (3B class) have been measured.** There is no paid API in this
  repo, so quality with a larger model is unknown. `stack` covers the wiring against a fake
  fake LLM server (no key, no cost); `live-ollama` and `ragas-ollama` use real local models.
- **Guardrail red-teaming is still one person's (mine) 122 cases**, not a professional
  red-team engagement, and attack detection on unseen phrasings is about 70% with the LLM layer and under 30% with
  rules alone -- see Red team above for what those numbers do and don't mean.
- **The runbooks and KPI data are synthetic**, so every eval score is close to ceiling and
  says more about the pipeline than about real-world quality. `scripts/import_kpis.py` can
  load real KPI exports; the runbooks still need replacing with real ones.
- **MCP is the default path for the agent's reads** (`TOOLS_VIA_MCP=0` turns it off). One long-lived
  server process per API worker is reused for every call (measured with a stub server: ~1.7 ms warm vs
  ~585 ms when a process was started per call; the real server adds its own first-call cost for imports and
  the embedding model). Costs: a second copy of the embedding model in memory per worker, and calls on one
  worker share a single pipe (tool calls are short DB/Qdrant reads, but this is a throughput ceiling that has
  not been load-tested). Covered by tests (read-only tool list, round trips, errors, reuse, restart after the
  server dies, concurrent callers) and by CI against the real Postgres/Qdrant.

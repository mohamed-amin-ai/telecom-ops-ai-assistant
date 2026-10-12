# Operations and configuration

### Production
```bash
# every ${VAR:?...} in docker-compose.yml and docker-compose.prod.yml must be set in .env
DOMAIN=ops.example.com ACME_EMAIL=you@example.com docker compose \
  -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
Adds Caddy (automatic TLS, HSTS, security headers; the only service reachable from outside
the Docker network -- `/metrics` is explicitly blocked on its public listener), multiple
uvicorn workers (`API_WORKERS`, default 4), Prometheus + alert rules, and Grafana
(`:3001` -- put it behind your own VPN or SSO proxy; this repo doesn't wire one). See
`ops/prometheus/alerts.yml` for the alert conditions and point `alerting.alertmanagers` in
`ops/prometheus/prometheus.yml` at Alertmanager, Slack, or PagerDuty.

**Backups:** `scripts/backup.sh` (`pg_dump`, retention via `RETENTION_DAYS`) and
`scripts/verify_backup.sh` (restores into a scratch database and compares row counts --
a backup that hasn't been restore-tested is a hope, not a backup). Qdrant isn't backed up:
the index rebuilds from `data/docs/` via `python -m scripts.ingest` (idempotent). Run
`backup.sh` on a schedule (cron, a Kubernetes CronJob) and `verify_backup.sh` after every
run or at minimum weekly.

**Secrets from files** (Docker/Kubernetes secrets, a secrets-manager volume): set
`FOO_FILE=/path` instead of `FOO` for any of the variables `scripts/entrypoint.sh` lists in
`SECRET_VARS`; the entrypoint reads the file into the environment variable before the app
starts, and refuses to start if the file doesn't exist.

## Auth and audit
Every user gets their own API key and one of three roles: `operator` (ask, open incidents)
< `approver` (also approve/reject) < `admin` (also read the audit log). Keys are random
tokens; only a SHA-256 hash is stored, so a lost key can't be recovered, only replaced.
`AUTH_REQUIRED=0` disables all of this -- local hacking only, never for anything reachable
by anyone else.

Every incident open, every decision, and every ticket creation is written to an
**append-only** audit table (`audit_log`; the table itself rejects `UPDATE`/`DELETE` at the
database level) before the action completes, attributed to the real signed-in user -- not a
shared key. A Postgres advisory lock keyed on the incident's thread id means two approvers
racing the same incident get one winner and a `409` for the other, never two tickets.
`GET /audit?thread_id=...` (admin only) reads it back.

## Observability
- **Metrics** (`/metrics`, Prometheus format): HTTP request counts/latency by route and
  status, LLM call counts/latency by model and outcome, guardrail blocks by label, rate-limit
  rejections by scope, auth failures by reason, approvals by decision, tickets created.
  Works with multiple uvicorn workers (`PROMETHEUS_MULTIPROC_DIR`, set automatically) --
  verified: 3 workers' counts sum correctly at `/metrics`.
- **Alerts** (`ops/prometheus/alerts.yml`): error-rate, p95 latency, LLM error rate, an auth
  failure spike, and "no tickets in 24h" (a silent pipeline reads as calm otherwise).
- **Logs:** structured JSON with a request id (`X-Request-ID`, generated or passed through)
  on every line, so one request's logs can be grepped out of a multi-worker stream.
- **Errors:** optional Sentry (`SENTRY_DSN`). Request bodies and the `X-API-Key` header are
  never sent (`send_default_pii=False`, `max_request_body_size="never"`,
  `include_local_variables=False`, and an event scrubber for the API-key header) --
  verified: fired a real exception with a live key and a sensitive question through a local
  Sentry-compatible receiver and confirmed neither appeared in the captured event.

## KPI data

**Real data:** per-cell operator counters (PRB utilisation, RRC/handover success) are not published openly;
the closest public sets are client-side UE traces (e.g. the Irish 5G trace dataset, GPL-3.0, RSRP/SNR/throughput),
which do not have this schema, so none is bundled. To use a real export from your OSS/PM system:
`python -m scripts.import_kpis export.csv` (long format) or `--wide --kpi-cols ... --rename "Vendor Name=kpi"`.
The seed below stays the default demo data. It is synthetic but shaped like real traffic: two daily busy hours, a night trough,
a small weekend dip, per-cell load character, autocorrelated noise, load-coupled success rates, missing samples and benign
blips. `tests/test_seed_kpis.py` checks, for every weekday, every hour of the day and 2 seeds, that exactly the 3 injected
faults are flagged and nothing else (an earlier, sparser version of this test passed while the PRB fault was missed at
about half of all hours; see the detector note under Evals). (A +30 spike on a cell already near 100% PRB would saturate; CELL_001 is kept at ~65% peak
so the fault stays visible.)

**Runbooks 23-27** are marked `STANDARDS-DERIVED`: written from the named 3GPP specs (RRC timers and
procedures, NAS reject causes, PRB counters, self-healing) with a "Standards references" section, but
written from knowledge of the specs and not checked clause by clause. Thresholds in them are examples.
Runbooks 01-22 remain synthetic.
`python -m scripts.ingest_kpis data.csv` (long format: `ts,cell_id,kpi,value`) or
`--wide` (`ts,cell_id,<kpi_1>,<kpi_2>,...`). Idempotent (a unique index means re-loading the
same file inserts nothing new); malformed rows are counted and skipped, not fatal.
`scripts/seed_kpis.py` remains for the synthetic demo data only.

## ITSM hand-off
Set `TICKET_WEBHOOK_URL` (and `TICKET_WEBHOOK_SECRET` for an HMAC-SHA256 `X-Signature-256`
header) to `POST` every approved ticket as JSON, with an `Idempotency-Key` header, to a real
ticketing system. Retries transient failures (5xx, network errors) with backoff; a 4xx is
not retried. Never raises: the ticket already exists in Postgres, and a flaky downstream
must not undo an approval that already happened. `webhook_status` on the ticket records the
outcome (`delivered` or `failed:<reason>`).

## Guardrails
- **Input** (`/ask`): PII redaction (emails, phone numbers, IMSI/IMEI/MSISDN-length IDs),
  deterministic rules for prompt injection and subscriber tracking (see Red team above for
  real numbers, not just a description), then a small LLM classifier (`GUARD_MODEL`) that
  blocks off-topic, injection and harmful requests.
- **Ingest-time**: every runbook chunk is scanned for indirect prompt injection (a document
  that tries to instruct the model) before being indexed; a match is logged and the chunk is
  quarantined, not indexed. `tests/test_redteam.py` confirms every real runbook in
  `data/docs/` passes this check and that a planted instruction is actually caught.
- **Alerts** (`/incident`): the free-text description gets the same redaction and rules (no
  LLM call). Cell ID and KPI name are pattern-validated.
- **Output**: PII redaction, and answers with neither a `[source#chunk]` citation nor an
  abstention get an "unverified" note.
- **Actions**: tools are read-only; tickets need `approver`+ and are recorded in the audit
  log before the ticket write happens.
- **API**: per-user rate limit plus a coarser per-IP ceiling underneath (for callers with no
  key at all), both Redis-backed and shared across replicas, falling back to per-replica
  in-process counting if Redis is unreachable. Optional CORS allowlist, optional path prefix
  for reverse-proxy deployments.
- Switches: `GUARDRAILS=0` disables all; `GUARD_LLM=0` keeps the rules and drops the
  classifier. If the classifier call fails it fails open (rules still apply) and logs a
  concise line, not a full stack trace (see "Found and fixed" below for why that matters).

## Self-hosted LLM with vLLM
Any model string `hosted_vllm/<served-model>` (for `LLM_MODEL`, `LLM_FALLBACK_MODEL`,
`JUDGE_MODEL`, `GUARD_MODEL`) is routed by `app/llm.py` to `VLLM_BASE_URL` with
`VLLM_API_KEY`; everything else (retries, Prometheus metrics, Langfuse tracing, Ollama
fallback) is unchanged, and RAGAS uses the same routing. To run the server:

```bash
# .env: VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct  VLLM_API_KEY=<random>  LLM_MODEL=hosted_vllm/Qwen/Qwen2.5-7B-Instruct
docker compose -f docker-compose.yml -f docker-compose.vllm.yml up -d --build
```
Needs an NVIDIA GPU and the NVIDIA container toolkit. **Status:** routing is unit-tested and the overlay's
config is validated in CI. vLLM 0.9.2 with Qwen2.5-7B-Instruct has been run on 2x Tesla T4 (tensor parallel 2) on
Kaggle via `kaggle/bench_kaggle.sh` (see [evaluation.md](evaluation.md)), but Kaggle has no Docker, so this compose
overlay itself (image tag, flags, memory fit for other models, first-start download time) has not been run. The
guardrail and RAGAS tables are for other models; re-run the evals against the model you choose.

## SSO, ITSM, tracing and alerts
- **SSO:** `Authorization: Bearer <OIDC JWT>` is accepted alongside API keys (`OIDC_*` settings; roles from a token claim;
  approver name recorded in the audit log). Unit-tested with generated keys, including expiry, audience, issuer,
  `alg=none`, key-confusion and missing-role cases; **not tested against a real identity provider**.
- **ITSM:** `TICKET_WEBHOOK_FORMAT=jira` posts a Jira REST v2 issue (`JIRA_PROJECT_KEY`, `TICKET_WEBHOOK_AUTH`);
  failed hand-offs are retried by `scripts/redeliver_tickets.py` with the same `Idempotency-Key`. Tested against a
  stubbed HTTP layer, **not a real Jira**.
- **Tracing:** OpenTelemetry spans around model turns, tool calls and ticket creation (off unless
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set); a test asserts no prompt or KPI content leaks into span attributes.
- **Alerts:** `AgentFallbackRateHigh` (model stops using tools) with a promtool unit test.
- **Runbook and SLOs:** `docs/oncall.md` (targets, alert -> action, disaster recovery).

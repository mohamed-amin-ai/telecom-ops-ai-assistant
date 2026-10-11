# On-call runbook and service levels

Status: these are **targets** wired into alerts and CI gates. They have been exercised against the
CI stack (fake LLM) and a 2x T4 benchmark, **not against production traffic**.

## Service levels (SLOs)
| SLO | Target | Where it is enforced |
|---|---|---|
| Availability of `/ready` | 99.5% monthly | `APIDown` (2 min), `DatabaseUnreachable` |
| Request errors | < 2% 5xx | `HighErrorRate`; CI soak gate `--max-error-rate 0.02` |
| `/ask` and `/incidents` latency | p95 < 20 s (fake LLM, CI); real-model figure is hardware-specific (2x T4: median ~30 s per incident, p95 up to ~57 s, so the target must be raised there) | `HighLatencyP95`; CI `--max-p95-s 20` |
| Approved tickets reach the ITSM | 100% within 1 h (retried by sweep) | `TicketWebhookFailing`, `scripts/redeliver_tickets.py` |
| Investigations use tools unaided | > 70% | `AgentFallbackRateHigh` |
| KPI data freshness | < 1 h | `KPIDataStale` |

## Alert -> first action
- **APIDown / DatabaseUnreachable**: `docker compose ps`, `docker compose logs api --tail 200`; Postgres first
  (`db_up`), then `/ready`. Roll back a bad deploy with `scripts/deploy.sh --rollback`.
- **HighErrorRate / HighLatencyP95**: check `LLMErrorRateHigh` first (slow or failing model server); then
  Redis/Qdrant health. The agent degrades to the fixed pipeline if the model cannot call tools.
- **LLMErrorRateHigh**: model server down or overloaded. Check `vllm`/`ollama` logs. The fallback model
  (`LLM_FALLBACK_MODEL`) is tried automatically; if both fail, `/incidents` returns an error and nothing is written.
- **AgentFallbackRateHigh**: the model stopped choosing tools (wrong model, missing `--enable-auto-tool-choice`
  on vLLM, or a bad prompt change). Run `python -m evals.run_tool_eval` against the live model.
- **TicketWebhookFailing**: the ticket exists in Postgres; only the ITSM hand-off failed
  (`tickets.webhook_status`). Fix the receiver, then `python -m scripts.redeliver_tickets` (same
  `Idempotency-Key`, so duplicates can be dropped). Schedule it every 15 min (cron / CronJob).
- **AuthFailureSpike**: look at `auth_failures_total{reason}` (`invalid_key`, `invalid_token`, `forbidden`).
  Revoke a leaked key with `UPDATE api_keys SET revoked_at = now() WHERE name = '...'` (effective within 30 s).
- **KPIDataStale**: the KPI feed stopped (`scripts/import_kpis.py` / ingestion). Detections on stale data are wrong.
- **ApprovalBacklog**: incidents wait for a human; page the approver rota. Nothing is created without approval.

## Disaster recovery
- Backup: `scripts/backup.sh` (pg_dump custom format, checksum, 14-day retention). Verify:
  `scripts/verify_backup.sh` restores into a scratch DB and compares row counts (CI runs this on every push).
- Qdrant is not backed up: rebuild with `python -m scripts.ingest` (idempotent). Restore order: Postgres, then
  Qdrant ingest, then `/ready`.
- Targets: RPO = backup interval (set it to <= 1 h); RTO = restore time + ingest (minutes at this data size, not measured at scale).

## Access (SSO)
API keys work as before. To accept OIDC bearer tokens set `OIDC_ISSUER`, `OIDC_AUDIENCE` and
`OIDC_JWKS_URL` (or `OIDC_JWKS_JSON`); map IdP groups to the `operator`/`approver`/`admin` claim named by
`OIDC_ROLE_CLAIM`. Tokens need `exp`, `iss`, `aud`; only RS*/ES* signatures are accepted. The approver's
name from the token (`OIDC_NAME_CLAIM`) is what lands in `tickets.approved_by` and the audit log.
**Verified with locally generated keys in unit tests, not against a real identity provider.**

## Tracing
Set `OTEL_EXPORTER_OTLP_ENDPOINT` (and optionally `OTEL_SERVICE_NAME`) to export OpenTelemetry spans
(`agent.model_turn`, `tool.<name>`, `agent.diagnose`, `agent.create_ticket`, `agent.summary`). Attributes carry
tool names, counts and outcomes only; no prompts, answers or KPI values.

## Migrations
Forward-only. Write each migration so the previous release still runs against the new schema, because
`deploy.sh --rollback` does not undo schema changes.

-- Makes KPI ingestion idempotent (re-loading the same file is a no-op). The unique index
-- includes ts, which TimescaleDB requires for a hypertable.
CREATE UNIQUE INDEX IF NOT EXISTS kpis_uniq ON kpis (cell_id, kpi, ts);

CREATE TABLE IF NOT EXISTS kpis (
  ts      timestamptz NOT NULL,
  cell_id text        NOT NULL,
  kpi     text        NOT NULL,
  value   double precision
);
SELECT create_hypertable('kpis', 'ts', if_not_exists => TRUE);
CREATE INDEX IF NOT EXISTS kpis_cell_kpi_ts ON kpis (cell_id, kpi, ts DESC);

CREATE TABLE IF NOT EXISTS tickets (
  id          bigserial PRIMARY KEY,
  thread_id   text NOT NULL,
  cell_id     text NOT NULL,
  kpi         text NOT NULL,
  alert       jsonb NOT NULL,
  diagnosis   text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS tickets_thread_id ON tickets (thread_id);
CREATE INDEX IF NOT EXISTS tickets_created_at ON tickets (created_at DESC);

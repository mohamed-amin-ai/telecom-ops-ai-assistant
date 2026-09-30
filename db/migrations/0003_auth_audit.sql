CREATE TABLE IF NOT EXISTS api_keys (
  id          bigserial PRIMARY KEY,
  name        text NOT NULL,
  role        text NOT NULL CHECK (role IN ('operator', 'approver', 'admin')),
  key_hash    text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at  timestamptz
);
CREATE INDEX IF NOT EXISTS api_keys_name ON api_keys (name);

CREATE TABLE IF NOT EXISTS audit_log (
  id         bigserial PRIMARY KEY,
  ts         timestamptz NOT NULL DEFAULT now(),
  actor      text NOT NULL,
  action     text NOT NULL,
  thread_id  text,
  detail     jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS audit_log_ts ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS audit_log_thread ON audit_log (thread_id);

-- Append-only: the audit trail is only worth anything if it can't be edited after the fact.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log;
CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

ALTER TABLE tickets ADD COLUMN IF NOT EXISTS approved_by text;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS webhook_status text;

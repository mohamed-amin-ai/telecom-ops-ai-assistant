-- One ticket per incident (thread): a retried approval must not create a second one.
-- Skipped (not failed) on a database that already holds duplicates, so the migration can
-- never block a deploy; create_ticket() checks for an existing row regardless.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM tickets GROUP BY thread_id HAVING count(*) > 1) THEN
    CREATE UNIQUE INDEX IF NOT EXISTS tickets_thread_id_uniq ON tickets (thread_id);
  END IF;
END $$;

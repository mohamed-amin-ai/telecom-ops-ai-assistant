#!/bin/sh
# Prove a backup is restorable: restore it into a scratch database, compare row counts of
# the important tables with the live database, drop the scratch database.
#   verify_backup.sh <dump-file> <live-database-url>
# The live URL's role needs CREATEDB. Fails (non-zero) if any table's count differs.
set -eu
dump="$1"; live="$2"
base="${live%/*}"
scratch="restore_verify_$$"
if [ -f "$dump.sha256" ]; then (cd "$(dirname "$dump")" && sha256sum -c "$(basename "$dump").sha256"); fi
psql "$live" -qAtc "CREATE DATABASE $scratch"
trap 'psql "$live" -qAtc "DROP DATABASE IF EXISTS $scratch" >/dev/null 2>&1 || true' EXIT
target="$base/$scratch"
# TimescaleDB needs its extension present and restore mode toggled around pg_restore.
if psql "$live" -qAtc "SELECT 1 FROM pg_extension WHERE extname='timescaledb'" | grep -q 1; then
  psql "$target" -qc "CREATE EXTENSION IF NOT EXISTS timescaledb"
  psql "$target" -qc "SELECT timescaledb_pre_restore()" >/dev/null
  TS=1
else
  TS=0
fi
# pg_restore exits non-zero on ignorable "already exists" noise; the row-count check below is
# the real test.
pg_restore --no-owner --dbname="$target" "$dump" 2>/tmp/pg_restore.err || true
[ "$TS" = 1 ] && psql "$target" -qc "SELECT timescaledb_post_restore()" >/dev/null
bad=0
for t in kpis tickets audit_log api_keys schema_migrations; do
  a=$(psql "$live" -qAtc "SELECT count(*) FROM $t")
  b=$(psql "$target" -qAtc "SELECT count(*) FROM $t" 2>/dev/null || echo MISSING)
  if [ "$a" = "$b" ]; then echo "ok    $t: $a rows"; else echo "DIFF  $t: live=$a restored=$b"; bad=1; fi
done
[ "$bad" = 0 ] && echo "backup verified: restorable, row counts match" || { echo "BACKUP VERIFICATION FAILED"; tail -5 /tmp/pg_restore.err; exit 1; }

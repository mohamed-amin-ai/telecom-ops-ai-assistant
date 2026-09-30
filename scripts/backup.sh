#!/bin/sh
# Logical backup of the application database (kpis, tickets, api_keys, audit_log, LangGraph
# checkpoints). Env: DATABASE_URL (required), BACKUP_DIR (/backups), RETENTION_DAYS (14).
# Qdrant is NOT backed up: the index is rebuilt from data/docs with `python -m scripts.ingest`
# (deterministic ids, idempotent), so the documents themselves are the source of truth.
set -eu
: "${DATABASE_URL:?DATABASE_URL is required}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
mkdir -p "$BACKUP_DIR"
ts=$(date -u +%Y%m%dT%H%M%SZ)
tmp="$BACKUP_DIR/.telecom-$ts.partial"
out="$BACKUP_DIR/telecom-$ts.dump"
pg_dump --format=custom --no-owner --dbname="$DATABASE_URL" --file="$tmp"
pg_restore --list "$tmp" > /dev/null   # never keep a dump that can't even be read back
mv "$tmp" "$out"
(cd "$BACKUP_DIR" && sha256sum "telecom-$ts.dump" > "telecom-$ts.dump.sha256")
find "$BACKUP_DIR" -type f \( -name 'telecom-*.dump' -o -name 'telecom-*.dump.sha256' \) \
  -mtime +"$RETENTION_DAYS" -delete
echo "backup ok: $out ($(du -h "$out" | cut -f1))"

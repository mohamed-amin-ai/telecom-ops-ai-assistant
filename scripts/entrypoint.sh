#!/bin/sh
# Docker-secrets support: for each variable in SECRET_VARS, if VAR_FILE=/path is set (and VAR
# is not), export VAR with the file's contents. Lets secrets come from mounted files (Docker
# or Kubernetes secrets, a secrets-manager volume) instead of plain environment variables.
# Only the listed variables are read: scanning every *_FILE would happily slurp things like
# LOG_FILE or CONFIG_FILE into the environment.
set -e
SECRET_VARS="${SECRET_VARS:-DATABASE_URL REDIS_URL BOOTSTRAP_API_KEYS TICKET_WEBHOOK_SECRET TICKET_WEBHOOK_URL SENTRY_DSN LANGFUSE_PUBLIC_KEY LANGFUSE_SECRET_KEY CHAINLIT_AUTH_SECRET}"
for name in $SECRET_VARS; do
  eval "file=\${${name}_FILE:-}"
  eval "current=\${${name}:-}"
  if [ -n "$file" ] && [ -z "$current" ]; then
    if [ ! -r "$file" ]; then
      echo "entrypoint: ${name}_FILE=$file is not readable" >&2
      exit 1
    fi
    value=$(cat "$file")
    export "$name=$value"
  fi
done
# Multi-process Prometheus metrics need a clean, writable directory at start.
if [ -n "${PROMETHEUS_MULTIPROC_DIR:-}" ]; then
  mkdir -p "$PROMETHEUS_MULTIPROC_DIR"
  rm -f "$PROMETHEUS_MULTIPROC_DIR"/* 2>/dev/null || true
fi
exec "$@"

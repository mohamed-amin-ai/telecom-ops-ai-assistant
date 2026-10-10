#!/bin/bash
# Gated deploy with automatic rollback, for a single-host compose install.
#   scripts/deploy.sh <tag>        build + start <tag>; roll back to the previous tag if unhealthy
#   scripts/deploy.sh --rollback   go back to the previously deployed tag
# Env: DC (docker compose command incl. -f flags; default: prod overlay),
#      STATE_DIR (default .deploy), HEALTH_URL (default http://localhost/api/ready via caddy),
#      HEALTH_TRIES (default 30, 5s apart).
# Not zero-downtime: the API restarts (a few seconds). Zero-downtime needs >1 host or a
# load balancer with two API replicas, which this script does not do.
set -euo pipefail
DC="${DC:-docker compose -f docker-compose.yml -f docker-compose.prod.yml}"
STATE_DIR="${STATE_DIR:-.deploy}"
HEALTH_TRIES="${HEALTH_TRIES:-30}"
mkdir -p "$STATE_DIR"
current_file="$STATE_DIR/current"; previous_file="$STATE_DIR/previous"

healthy() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    # ready = Postgres + Qdrant + Redis reachable; checked inside the api container so it
    # does not depend on DNS/TLS of the public name.
    if $DC exec -T api python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/ready', timeout=5).status==200 else 1)" >/dev/null 2>&1; then
      return 0
    fi
    sleep "${HEALTH_SLEEP:-5}"
  done
  return 1
}

start() {  # start <tag> [--build]
  export APP_TAG="$1"
  if [ "${2:-}" = "--build" ]; then $DC build api ui migrate; fi
  $DC run --rm migrate
  # `up` exits non-zero when the new api never turns healthy (ui depends on it); that is
  # the case this script exists to handle, so it must not abort here: healthy() decides.
  $DC up -d --no-build api ui || echo "warning: compose up reported a failure for $1" >&2
}

if [ "${1:-}" = "--rollback" ]; then
  [ -s "$previous_file" ] || { echo "no previous deploy recorded" >&2; exit 2; }
  target=$(cat "$previous_file"); cur=$(cat "$current_file" 2>/dev/null || true)
  echo "rolling back ${cur:-?} -> $target"
  start "$target"
  healthy || { echo "ROLLBACK TARGET $target IS NOT HEALTHY" >&2; exit 1; }
  echo "$target" > "$current_file"; echo "$cur" > "$previous_file"
  exit 0
fi

tag="${1:?usage: deploy.sh <tag> | --rollback}"
prev=$(cat "$current_file" 2>/dev/null || true)
echo "deploying $tag (current: ${prev:-none})"
start "$tag" --build
if healthy; then
  [ -n "$prev" ] && echo "$prev" > "$previous_file"
  echo "$tag" > "$current_file"
  echo "deployed $tag"
  exit 0
fi
echo "deploy of $tag FAILED health check" >&2
$DC logs --tail 40 api >&2 || true
if [ -n "$prev" ]; then
  echo "rolling back to $prev" >&2
  start "$prev"
  healthy && { echo "rolled back to $prev"; exit 1; }
  echo "ROLLBACK TO $prev ALSO UNHEALTHY: manual intervention needed" >&2
fi
exit 1

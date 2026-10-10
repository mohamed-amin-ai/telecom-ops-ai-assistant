#!/bin/bash
# Compact container diagnostics for CI annotations: state of every container, and the log tail
# of any that is not running/healthy. Env: DC = the docker compose command with its -f flags.
DC="${DC:?}"
echo "== containers"
$DC ps -a --format '{{.Service}}\t{{.State}}\t{{.Status}}' 2>&1 | sort
echo
for svc in $($DC ps -a --format '{{.Service}}\t{{.State}}\t{{.Status}}' 2>/dev/null | awk -F'\t' '$2!="running" || $3 ~ /unhealthy|starting/ {print $1}'); do
  echo "== log tail: $svc"
  $DC logs --no-color --tail 25 "$svc" 2>&1 | cut -c1-220
  echo
done

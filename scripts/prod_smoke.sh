#!/bin/bash
# Assertions against a running production-overlay stack (TLS proxy, Prometheus, Grafana).
# Env: PROMETHEUS_COMPOSE (the docker compose command with the right -f flags),
#      GRAFANA_BASIC_USER/PASS (proxy basic auth), GRAFANA_ADMIN_PASS, API_KEY.
set -u
DC="${DC:?set DC to the docker compose command including -f flags}"
fail=0
check() {  # check "description" expected command...
  local desc="$1" want="$2"; shift 2
  local got; got=$("$@" 2>/dev/null) || true
  if [ "$got" = "$want" ]; then echo "PASS  $desc"; else echo "FAIL  $desc (got '$got', want '$want')"; fail=1; fi
}
code() { curl -sk -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }
ask()  { curl -sk -o /dev/null -w '%{http_code}' --max-time 60 -X POST https://localhost/api/ask \
           -H 'content-type: application/json' -d '{"question":"What is the ping-pong handover threshold?"}' "$@"; }
promq() {  # promq 'expr' -> first result value, or 'none'
  $DC exec -T prometheus wget -qO- "http://localhost:9090/api/v1/query?query=$(python3 -c 'import sys,urllib.parse; print(urllib.parse.quote(sys.argv[1]))' "$1")" \
    | python3 -c "import json,sys; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else 'none')"
}

echo "== proxy: TLS, routing, exposure"
check "UI served over TLS" 200 code https://localhost/
check "plain HTTP redirects to HTTPS" 308 code http://localhost/
check "API reachable under /api (prefix stripped)" 200 code https://localhost/api/health
check "API refuses a request with no key" 401 ask
check "API answers with a key" 200 ask -H "X-API-Key: $API_KEY"
check "public /metrics hidden" 404 code https://localhost/metrics
check "public /api/metrics hidden" 404 code https://localhost/api/metrics
check "grafana refuses without proxy basic auth" 401 code https://localhost/grafana/api/health
check "grafana reachable with proxy basic auth" 200 code -u "$GRAFANA_BASIC_USER:$GRAFANA_BASIC_PASS" https://localhost/grafana/api/health
for port in 8000 8080 3001 6333 5432 6379 9090; do
  check "internal port $port is not published on the host" 000 code "http://localhost:$port/"
done
hdr=$(curl -sk -D - -o /dev/null https://localhost/ | tr -d '\r')
check "HSTS header set" 1 bash -c "echo '$hdr' | grep -ci '^strict-transport-security: max-age=31536000' || true"

echo "== traffic, then metrics pipeline"
for _ in $(seq 1 25); do ask -H "X-API-Key: $API_KEY" > /dev/null; done
up=none
for _ in $(seq 1 30); do up=$(promq 'up{job="api"}'); [ "$up" = "1" ] && break; sleep 5; done
check "prometheus scrapes the API via the internal listener" 1 echo "$up"
seen=0
for _ in $(seq 1 30); do
  seen=$(promq 'sum(http_requests_total{route="/ask"})'); python3 -c "import sys; sys.exit(0 if float('$seen' if '$seen' != 'none' else 0) >= 25 else 1)" && break; sleep 5
done
check "request counters reached prometheus (>= 25 /ask requests, multi-worker aggregated)" 1 \
  python3 -c "print(1 if '$seen' != 'none' and float('$seen') >= 25 else 0)"
check "quality metric present: answers_total" 1 python3 -c "print(1 if '$(promq 'sum(answers_total)')' != 'none' else 0)"
check "KPI freshness gauge present and fresh" 1 python3 -c "
v='$(promq 'kpi_data_age_seconds')'; print(1 if v != 'none' and float(v) < 3600 else 0)"
check "database reachable (db_up)" 1 echo "$(promq 'db_up')"

echo "== alert rules loaded and evaluating without errors"
want=$(grep -c '^      - alert:' ops/prometheus/alerts.yml)
rules=none
for _ in $(seq 1 30); do
  rules=$($DC exec -T prometheus wget -qO- http://localhost:9090/api/v1/rules | python3 -c "
import json,sys
g=json.load(sys.stdin)['data']['groups']
rs=[r for x in g for r in x['rules']]
ok=all(r.get('health')=='ok' and not r.get('lastError') for r in rs)
print(f'{len(rs)}:{ok}')") || true
  [ "$rules" = "$want:True" ] && break; sleep 5
done
check "all $want alert rules loaded, healthy, no evaluation errors" "$want:True" echo "$rules"

echo "== grafana"
GBASIC=$(printf 'admin:%s' "$GRAFANA_ADMIN_PASS" | base64 -w0)
dash=$($DC exec -T grafana wget -qO- --header "Authorization: Basic $GBASIC" 'http://localhost:3000/grafana/api/search?query=Telecom' 2>/dev/null | grep -c 'Telecom Ops Assistant' || true)
check "dashboard provisioned" 1 echo "$([ "$dash" -ge 1 ] && echo 1 || echo 0)"
ds=$($DC exec -T grafana wget -qO- --header "Authorization: Basic $GBASIC" 'http://localhost:3000/grafana/api/datasources' 2>/dev/null | grep -c '"type":"prometheus"' || true)
check "prometheus datasource provisioned" 1 echo "$([ "$ds" -ge 1 ] && echo 1 || echo 0)"

[ "$fail" = 0 ] || $DC logs --tail 40 grafana 2>&1 | tail -40
[ "$fail" = 0 ] && echo "ALL PASSED" || echo "SOME CHECKS FAILED"
exit $fail

#!/usr/bin/env bash
# Starts the fake fatsecret + the API, runs Locust headless, prints a summary.
# Usage: perf/run_loadtest.sh <label> [users] [seconds] [workers]
set -euo pipefail
LABEL=${1:-run}; USERS=${2:-50}; SECONDS_=${3:-60}; WORKERS=${4:-1}
cd "$(dirname "$0")/.."
export FATSECRET__CLIENT_ID=load FATSECRET__CLIENT_SECRET=load \
  FATSECRET__TOKEN_URL=http://127.0.0.1:9100/connect/token \
  FATSECRET__BASE_URL=http://127.0.0.1:9100/rest \
  AUTH__JWT_SECRET="${AUTH__JWT_SECRET:-load-test-secret-0123456789-abcdefghijklmnop}" \
  CACHE__BACKEND=redis CACHE__REDIS_URL="${CACHE__REDIS_URL:-redis://localhost:6379/9}" \
  SECURITY__RATE_LIMIT_ENABLED=false LOG_LEVEL=INFO LOG_JSON=true

# A previous run may still be shutting down: wait until both ports are free.
for _ in $(seq 1 60); do
  (curl -s localhost:8090 >/dev/null || curl -s localhost:9100 >/dev/null) || break
  sleep 0.5
done

uv run python perf/fake_fatsecret.py --port 9100 --latency-ms 40 & FAKE=$!
uv run uvicorn nutritionist.main:create_app --factory --port 8090 --workers "$WORKERS" \
  --no-server-header --timeout-keep-alive 75 > "/tmp/api-$LABEL.log" 2>&1 & API=$!
trap 'kill $FAKE $API 2>/dev/null || true' EXIT
ready=""
for _ in $(seq 1 120); do
  kill -0 "$API" 2>/dev/null || { echo "API process exited, see /tmp/api-$LABEL.log" >&2; exit 1; }
  curl -sf localhost:8090/health/live >/dev/null && curl -sf localhost:9100/connect/token -X POST >/dev/null \
    && { ready=1; break; }
  sleep 0.5
done
[ -n "$ready" ] || { echo "API or fake fatsecret did not start" >&2; exit 1; }

if [ "${MODE:-mixed}" = "steady" ]; then
  uv run python perf/seed_users.py --base http://localhost:8090 --users "$USERS"
fi
MODE=${MODE:-mixed} uv run --group perf locust -f perf/locustfile.py --headless -u "$USERS" -r 10 \
  -t "${SECONDS_}s" -H http://localhost:8090 --csv "perf/results/$LABEL" --only-summary \
  > /dev/null 2>&1 || true
python3 - "$LABEL" <<'PY'
import csv, sys
rows = list(csv.DictReader(open(f"perf/results/{sys.argv[1]}_stats.csv")))
print(f"{'endpoint':28} {'reqs':>6} {'fail':>5} {'p50':>6} {'p95':>6} {'p99':>6} {'rps':>7}")
for r in rows:
    print(f"{r['Name'][:28]:28} {r['Request Count']:>6} {r['Failure Count']:>5} "
          f"{r['50%']:>6} {r['95%']:>6} {r['99%']:>6} {float(r['Requests/s']):>7.1f}")
PY

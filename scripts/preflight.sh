#!/usr/bin/env bash
set -euo pipefail

FAIL_COUNT=0
FAILURES=()

fail() {
    echo "FAIL: $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
    FAILURES+=("$1")
}

cd "$(dirname "$0")/.."

LIVE_PORT="${LIVE_ENGINE_PORT:-18080}"
ASYNC_PORT="${ASYNC_WORKER_PORT:-18081}"
ARI_HOST="${ASTERISK_HOST:-127.0.0.1}"
ARI_PORT="${ASTERISK_ARI_PORT:-8088}"
ARI_USER="${ASTERISK_ARI_USER:-openclaw}"
ARI_PASS="${ASTERISK_ARI_PASSWORD:-}"

echo "=== Preflight Check ==="
echo "LIVE_ENGINE_PORT: $LIVE_PORT"
echo "ASYNC_WORKER_PORT: $ASYNC_PORT"
echo "ASTERISK_ARI: ${ARI_HOST}:${ARI_PORT}"
echo ""

echo "[1/6] Compose syntax check"
if docker compose config >/dev/null 2>&1; then
    echo "  OK: compose config valid"
else
    fail "compose config invalid"
fi

echo "[2/6] Build core services"
if docker compose build live-engine async-worker >/tmp/anrufwerker_build.log 2>&1; then
    echo "  OK: build succeeded"
else
    fail "build failed - see /tmp/anrufwerker_build.log"
fi

echo "[3/6] Start core services"
OUTBOUND_ENABLED=true OUTBOUND_ALLOWED_HOURS=00:00-23:59 ASTERISK_ORIGINATE_ENABLED=false \
  docker compose up -d --no-deps live-engine async-worker >/tmp/anrufwerker_up.log 2>&1 || fail "docker compose up failed"

echo "[4/6] Health checks"
sleep 5

if curl -sf --max-time 10 "http://127.0.0.1:${LIVE_PORT}/health" >/tmp/anrufwerker_live_health.json 2>&1; then
    LIVE_OK=$(python3 -c "import json; print(json.load(open('/tmp/anrufwerker_live_health.json')).get('ok', False))" 2>/dev/null || echo "false")
    if [ "$LIVE_OK" = "True" ]; then
        echo "  OK: live-engine healthy"
    else
        fail "live-engine /health returned non-ok"
    fi
else
    fail "live-engine /health unreachable"
fi

if curl -sf --max-time 10 "http://127.0.0.1:${ASYNC_PORT}/health" >/tmp/anrufwerker_worker_health.json 2>&1; then
    ASYNC_OK=$(python3 -c "import json; print(json.load(open('/tmp/anrufwerker_worker_health.json')).get('ok', False))" 2>/dev/null || echo "false")
    if [ "$ASYNC_OK" = "True" ]; then
        echo "  OK: async-worker healthy"
    else
        fail "async-worker /health returned non-ok"
    fi
else
    fail "async-worker /health unreachable"
fi

echo "[5/6] ARI reachability probe"
set +e
HTTP_CODE=$(curl -s -o /tmp/anrufwerker_ari_probe.txt -w '%{http_code}' --max-time 10 -u "${ARI_USER}:${ARI_PASS}" "http://${ARI_HOST}:${ARI_PORT}/ari/asterisk/info" 2>&1)
set -e

if [ "$HTTP_CODE" = "200" ]; then
    echo "  OK: Asterisk ARI responds (HTTP 200)"
elif [ "$HTTP_CODE" = "401" ]; then
    echo "  WARN: Asterisk ARI auth required (HTTP 401) - check ASTERISK_ARI_PASSWORD"
else
    fail "Asterisk ARI unreachable (HTTP $HTTP_CODE)"
fi

echo "[6/6] Outbound dry-run (optional, skipped in preflight)"

echo ""
echo "=== Summary ==="
if [ $FAIL_COUNT -eq 0 ]; then
    echo "All checks PASSED"
    echo "teardown..."
    docker compose down >/dev/null 2>&1 || true
    exit 0
else
    echo "FAILED: $FAIL_COUNT check(s)"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
    echo "teardown..."
    docker compose down >/dev/null 2>&1 || true
    exit 1
fi

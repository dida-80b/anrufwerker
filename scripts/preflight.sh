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

DASHBOARD_PORT="${DASHBOARD_PORT:-8083}"
ASYNC_PORT="${ASYNC_WORKER_PORT:-8087}"
PIPER_PORT="${PIPER_PORT:-5150}"
ARI_HOST="${ASTERISK_HOST:-127.0.0.1}"
ARI_PORT="${ASTERISK_ARI_PORT:-8088}"
ARI_USER="${ASTERISK_ARI_USER:-}"
ARI_PASS="${ASTERISK_ARI_PASSWORD:-}"

echo "=== Preflight Check ==="
echo "DASHBOARD:    http://127.0.0.1:${DASHBOARD_PORT}"
echo "ASYNC_WORKER: http://127.0.0.1:${ASYNC_PORT}"
echo "PIPER:        http://127.0.0.1:${PIPER_PORT}"
echo "ARI:          ${ARI_HOST}:${ARI_PORT}"
echo ""

echo "[1/5] Compose syntax check"
if docker compose config >/dev/null 2>&1; then
    echo "  OK: compose config valid"
else
    fail "compose config invalid"
fi

echo "[2/5] Build core services"
if docker compose build sip-bridge piper async-worker >/tmp/anrufwerker_build.log 2>&1; then
    echo "  OK: build succeeded"
else
    fail "build failed — see /tmp/anrufwerker_build.log"
fi

echo "[3/5] Start core services"
docker compose up -d >/tmp/anrufwerker_up.log 2>&1 || fail "docker compose up failed"
sleep 5

echo "[4/5] Health checks"
for name in "dashboard:${DASHBOARD_PORT}" "async-worker:${ASYNC_PORT}" "piper:${PIPER_PORT}"; do
    svc="${name%%:*}"
    port="${name##*:}"
    if curl -sf --max-time 10 "http://127.0.0.1:${port}/health" >/dev/null 2>&1; then
        echo "  OK: ${svc} healthy"
    else
        fail "${svc} /health unreachable on port ${port}"
    fi
done

echo "[5/5] ARI reachability probe"
set +e
HTTP_CODE=$(curl -s -o /tmp/anrufwerker_ari_probe.txt -w '%{http_code}' \
    --max-time 10 -u "${ARI_USER}:${ARI_PASS}" \
    "http://${ARI_HOST}:${ARI_PORT}/ari/asterisk/info" 2>&1)
set -e

if [ "$HTTP_CODE" = "200" ]; then
    echo "  OK: Asterisk ARI responds (HTTP 200)"
elif [ "$HTTP_CODE" = "401" ]; then
    echo "  WARN: Asterisk ARI auth required (HTTP 401) — prüfe ASTERISK_ARI_PASSWORD"
else
    echo "  WARN: Asterisk ARI nicht erreichbar (HTTP ${HTTP_CODE}) — standalone-Profil aktiv?"
fi

echo ""
echo "=== Summary ==="
if [ $FAIL_COUNT -eq 0 ]; then
    echo "Alle Checks PASSED"
    exit 0
else
    echo "FAILED: $FAIL_COUNT check(s)"
    for f in "${FAILURES[@]}"; do
        echo "  - $f"
    done
    exit 1
fi

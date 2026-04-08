# Test-Setup: Inbound-Pfad Verifikation

## Services starten

```bash
# 1. Basis-Services (live-engine, async-worker, asterisk)
docker compose up -d

# 2. Health-Checks
curl http://localhost:18080/health
curl http://localhost:18081/health

# 3. Asterisk CLI
docker exec -it anrufwerker-asterisk asterisk -rvvv
```

## Health/Probe Checks

| Service | Check | Erwartete Antwort |
|---------|-------|-------------------|
| live-engine | `GET /health` | `{"ok": true, "ari_client": true}` |
| async-worker | `GET /health` | `{"ok": true}` |
| asterisk | `docker exec asterisk asterisk -rx "core show version"` | Versionsinfo |
| ARI | `curl -u openclaw:changeme http://asterisk:8088/ari/api-docs/` | Swagger UI |

## Inbound-Signalfluss verifizieren

### 1. ARI App-Registration prüfen
```bash
curl -u openclaw:changeme http://localhost:18080/ari/applications
# oder im Container:
docker exec anrufwerker-asterisk asterisk -rx "ari show users"
```

### 2. SIP-Endpoint prüfen
```bash
docker exec anrufwerker-asterisk asterisk -rx "pjsip show endpoints"
docker exec anrufwerker-asterisk asterisk -rx "pjsip show transports"
```

### 3. Inbound-Call simulieren (via AMI oder originate)
```bash
# Via ARI originate zu Testzwecken
curl -u openclaw:changeme -X POST \
  "http://localhost:8088/ari/channels?endpoint=PJSIP/100@fritzbox&app=anrufwerker&channelId=test-123" \
  -H "Content-Type: application/json"
```

### 4. Inbound-Endpoint testen
```bash
# Direkt am Inbound-Endpoint
curl -X POST http://localhost:18080/inbound/call/start \
  -H "Content-Type: application/json" \
  -d '{"channel_id": "test-channel-001", "caller_number": "+49123456789"}'
```

### 5. Queue-Jobs prüfen
```bash
curl http://localhost:18081/job/status/<call_id>
```

## Manuelle Inbound-Simulation

### Option A: Asterisk originate
```bash
docker exec anrufwerker-asterisk asterisk -rx "channel originate PJSIP/100@fritzbox extension s@anrufwerker-inbound"
```

### Option B: SIP-Invite von externem Client
- SIP-Client (z.B. Linphone, Zoiper) an localhost:5060 registrieren
- Anruf zu +49... (DID) starten

## Log-Verifikation

```bash
# Live-Engine Logs
docker logs anrufwerker-live-engine -f | grep -i inbound

# Asterisk Logs
docker logs anrufwerker-asterisk -f | grep -i stasis

# Alle Services
docker compose logs -f live-engine asterisk
```

## Erwartetes Verhalten

1. **Anruf kommt rein** → Asterisk leitet an Stasis-App "anrufwerker" weiter
2. **ARI-Client erhält StasisStart** → Loggt eingehenden Anruf
3. **Inbound-Call-Endpoint** → Nimmt Call entgegen,答, Queued
4. **Call-Ende** → StasisEnd → Hangup

## Rollback-Prüfpunkte

- `ASTERISK_ARI_PASSWORD` muss in sync sein (asterisk env + live-engine env)
- Port 5060 UDP und 8088 TCP müssen erreichbar sein
- `depends_on` in docker-compose.yml stellt sicher, dass asterisk nach live-engine startet

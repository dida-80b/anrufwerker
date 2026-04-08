# Troubleshooting Guide

## Port-Konflikte

### Symptom
```
Error: bind: address already in use
```

### Diagnose
```bash
# Prüfe welche Ports belegt sind
ss -tlnp | grep -E '18080|18081|5060|8088'
# oder
netstat -tlnp | grep -E '18080|18081|5060|8088'
```

### Lösung
1. Identify blocking process: `lsof -i :18080`
2. Stop blocking service or change port in `.env`:
   ```bash
   LIVE_ENGINE_PORT=18081
   ASYNC_WORKER_PORT=18082
   ```

---

## ARI Authentication

### Symptom
```
 Asterisk ARI unreachable (HTTP 401)
```

### Diagnose
```bash
# Test ARI manually
curl -u openclaw:YOUR_PASSWORD http://asterisk:8088/ari/asterisk/info
```

### Lösung
1. Set password in `.env`:
   ```
   ASTERISK_ARI_PASSWORD=your_secure_password
   ```
2. Ensure Asterisk ARI user exists in `asterisk/etc/asterisk/http.conf`:
   ```
   [general]
   enabled=yes
   bindport=8088
   bindaddr=0.0.0.0
   
   [openclaw]
   type=user
   password=your_secure_password
   read=all
   write=all
   ```

---

## host.docker.internal

### Symptom
```
connection refused: Ollama not reachable
```

### Diagnose
```bash
# Test from inside container
docker exec anrufwerker-live-engine curl -f http://host.docker.internal:11434/api/tags
```

### Ursachen & Lösungen

1. **Linux**: `extra_hosts` erforderlich (bereits in compose.yml)
   ```yaml
   extra_hosts:
     - "host.docker.internal:host-gateway"
   ```

2. **Ollama nicht auf Host gestartet**:
   ```bash
   # Auf Host starten
   ollama serve
   # Oder als Service
   sudo systemctl enable ollama
   ```

3. **Ollama Port anders als 11434**:
   ```bash
   # Prüfen
   curl http://localhost:11434/api/tags
   
   # Anpassen in .env
   OLLAMA_HOST=http://host.docker.internal:11434
   ```

4. **Firewall blockiert**:
   ```bash
   # Linux: Firewall prüfen
   sudo ufw allow 11434/tcp
   ```

---

## Asterisk Erreichbarkeit

### Symptom
```
Error: connect: connection refused
```

### Diagnose
```bash
# Prüfe ob Asterisk läuft
docker ps | grep asterisk

# Test ARI von Host
curl -u openclaw:pass http://localhost:8088/ari/asterisk/info

# Test aus Container
docker exec anrufwerker-live-engine curl -f http://asterisk:8088/ari/asterisk/info
```

### Lösung
1. Starte Asterisk: `docker compose up -d asterisk`
2. Prüfe Port 5060/UDP frei
3. Prüfe Asterisk Config in `asterisk/etc/`

---

## Preflight-Check Fehler

### Testausführung
```bash
# Vollständiger Preflight
make preflight

# Nur Compose-Prüfung
make check

# Manuell
./scripts/preflight.sh
```

### Exit-Codes
- `0`: Alle Checks bestanden
- `1`: Ein oder mehr Checks fehlgeschlagen

### Logs
- Build: `/tmp/anrufwerker_build.log`
- Up: `/tmp/anrufwerker_up.log`
- Health: `/tmp/anrufwerker_*_health.json`
- ARI: `/tmp/anrufwerker_ari_probe.txt`

---

## Cutover-Checkliste

- [ ] `make preflight` → Exit 0
- [ ] `docker compose ps` → alle Services "Up"
- [ ] Health-Endpoints respondieren:
  - `curl http://localhost:18080/health` → `{"ok":true}`
  - `curl http://localhost:18081/health` → `{"ok":true}`
- [ ] ARI erreichbar: `curl -u openclaw:pass http://asterisk:8088/ari/asterisk/info`
- [ ] Ollama auf Host: `curl http://localhost:11434/api/tags`
- [ ] Outbound-Call Test (optional):
  ```bash
  curl -X POST http://localhost:18080/outbound/call \
    -H 'Content-Type: application/json' \
    -d '{"to":"+491701234567","mission":"Test","mission_type":"test"}'
  ```

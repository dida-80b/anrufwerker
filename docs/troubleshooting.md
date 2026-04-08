# Troubleshooting

## Port-Konflikte

### Symptom
```
Error: bind: address already in use
```

### Diagnose
```bash
ss -tlnp | grep -E '5003|5150|8083|8087|9093|5060|8088'
```

### Lösung
Belegenden Prozess identifizieren und beenden, oder Port in `.env` überschreiben:
```bash
BRIDGE_PORT=5004
AUDIOSOCKET_PORT=9094
```

---

## ARI Authentication

### Symptom
```
Asterisk ARI unreachable (HTTP 401)
```

### Diagnose
```bash
curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD \
  http://localhost:8088/ari/asterisk/info
```

### Lösung
1. `.env` prüfen — `ASTERISK_ARI_USER` und `ASTERISK_ARI_PASSWORD` müssen mit `asterisk/etc/ari.conf` übereinstimmen
2. Asterisk neu starten: `docker compose restart asterisk`

---

## Ollama nicht erreichbar

### Symptom
```
connection refused: Ollama not reachable
```

### Diagnose
```bash
# Auf Host testen
curl http://localhost:11434/api/tags

# Aus Container testen
docker exec anrufwerker-sip-bridge curl -f http://host.docker.internal:11434/api/tags
```

### Lösung
1. Ollama auf Host starten: `ollama serve`
2. Modell prüfen: `ollama list` — Modell aus `.env OLLAMA_MODEL` muss vorhanden sein
3. Auf Linux: `extra_hosts: host.docker.internal:host-gateway` ist bereits in compose.yml gesetzt

---

## Asterisk nicht erreichbar

### Symptom
```
Error: connect: connection refused
```

### Diagnose
```bash
docker ps | grep asterisk
docker exec anrufwerker-asterisk asterisk -rx "pjsip show endpoints"
```

### Lösung
```bash
# Standalone-Profil startet eigenen Asterisk
docker compose --profile standalone up -d asterisk

# Oder externen Asterisk konfigurieren
# ASTERISK_HOST in .env auf IP des Asterisk-Servers setzen
```

---

## Piper antwortet nicht

### Symptom
```
piper /health unreachable
```

### Diagnose
```bash
curl http://localhost:5150/health
docker logs anrufwerker-piper
```

### Lösung
1. Piper-Voice vorhanden? `ls data/piper-voices/`
2. Voice-Datei herunterladen (siehe README Quickstart)
3. `docker compose restart piper`

---

## TTS klingt falsch / kein Audio

### Diagnose
```bash
# Piper direkt testen
curl -s -X POST http://localhost:5150/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Test", "voice": "de_DE-thorsten-high"}' \
  --output /tmp/test.wav && aplay /tmp/test.wav

# Verfügbare Stimmen anzeigen
curl http://localhost:5150/voices
```

### Lösung
`PIPER_VOICE` in `.env` muss exakt dem Dateinamen ohne `.onnx` entsprechen.

---

## Whisper nicht erreichbar

### Diagnose
```bash
curl http://localhost:8090/health   # externe Whisper-Instanz
curl http://localhost:8091/health   # standalone-Profil
```

### Lösung
- `WHISPER_URL` in `.env` auf laufende Whisper-Instanz zeigen lassen
- Standalone starten: `docker compose --profile standalone up -d whisper-gpu`

---

## Preflight-Check

```bash
make preflight
# oder
./scripts/preflight.sh
```

Exit-Codes: `0` = OK, `1` = Fehler

---

## Cutover-Checkliste

- [ ] `make preflight` → Exit 0
- [ ] `docker compose ps` → alle Services "Up"
- [ ] Health-Endpoints:
  - `curl http://localhost:8083/health` → Dashboard
  - `curl http://localhost:8087/health` → Async-Worker
  - `curl http://localhost:5150/health` → Piper TTS
- [ ] Ollama: `curl http://localhost:11434/api/tags`
- [ ] Asterisk ARI: `curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD http://localhost:8088/ari/asterisk/info`
- [ ] Dashboard öffnen: `http://localhost:8083` → Login → Firmendaten eintragen

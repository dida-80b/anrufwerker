# Troubleshooting

## Port conflicts

### Symptom
```
Error: bind: address already in use
```

### Diagnosis
```bash
ss -tlnp | grep -E '5003|5150|8083|8087|9093|5060|8088'
```

### Fix
Identify and stop the conflicting process, or override the port in `.env`:
```bash
BRIDGE_PORT=5004
AUDIOSOCKET_PORT=9094
```

---

## ARI authentication

### Symptom
```
Asterisk ARI unreachable (HTTP 401)
```

### Diagnosis
```bash
curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD \
  http://localhost:8088/ari/asterisk/info
```

### Fix
1. Check `.env` — `ASTERISK_ARI_USER` and `ASTERISK_ARI_PASSWORD` must match the Asterisk template configuration
2. Restart Asterisk: `docker compose restart asterisk`

---

## Ollama unreachable

### Symptom
```
connection refused: Ollama not reachable
```

### Diagnosis
```bash
# Test on host
curl http://localhost:11434/api/tags

# Test from container
docker exec anrufwerker-sip-bridge curl -f http://host.docker.internal:11434/api/tags
```

### Fix
1. Start Ollama on the host: `ollama serve`
2. Check model: `ollama list` — the model from `.env OLLAMA_MODEL` must be present
3. On Linux: `extra_hosts: host.docker.internal:host-gateway` is already set in compose.yml

---

## Asterisk unreachable

### Symptom
```
Error: connect: connection refused
```

### Diagnosis
```bash
docker ps | grep asterisk
docker exec anrufwerker-asterisk asterisk -rx "pjsip show endpoints"
```

### Fix
```bash
# Standalone profile starts its own Asterisk
docker compose --profile standalone up -d asterisk

# Or configure an external Asterisk
# Set ASTERISK_HOST in .env to the IP of the Asterisk server
```

---

## Piper not responding

### Symptom
```
piper /health unreachable
```

### Diagnosis
```bash
curl http://localhost:5150/health
docker logs anrufwerker-piper
```

### Fix
1. Is the Piper voice present? `ls data/piper-voices/`
2. Download the voice file (see README quickstart)
3. `docker compose restart piper`

---

## TTS sounds wrong / no audio

### Diagnosis
```bash
# Test Piper directly
curl -s -X POST http://localhost:5150/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Test", "voice": "de_DE-thorsten-high"}' \
  --output /tmp/test.wav && aplay /tmp/test.wav

# List available voices
curl http://localhost:5150/voices
```

### Fix
`PIPER_VOICE` in `.env` must exactly match the filename without `.onnx`.

---

## Whisper unreachable

### Diagnosis
```bash
curl http://localhost:8090/health   # external Whisper instance
curl http://localhost:8091/health   # standalone profile
```

### Fix
- Point `WHISPER_URL` in `.env` to a running Whisper instance
- Start standalone: `docker compose --profile standalone up -d whisper-gpu`

---

## Preflight check

```bash
make preflight
# or
./scripts/preflight.sh
```

Exit codes: `0` = OK, `1` = error

---

## Go-live checklist

- [ ] `make preflight` → exit 0
- [ ] `docker compose ps` → all services "Up"
- [ ] Health endpoints:
  - `curl http://localhost:8083/health` → Dashboard
  - `curl http://localhost:8087/health` → Async worker
  - `curl http://localhost:5150/health` → Piper TTS
- [ ] Ollama: `curl http://localhost:11434/api/tags`
- [ ] Asterisk ARI: `curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD http://localhost:8088/ari/asterisk/info`
- [ ] Open dashboard: `http://localhost:8083` → Login → Enter company details

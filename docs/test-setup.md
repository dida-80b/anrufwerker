# Setup & Testing

## Quickstart from clone

```bash
git clone git@github.com:dida-80b/anrufwerker.git
cd anrufwerker

# 1. Configuration
cp .env.example .env
# Open .env and fill in required fields (ASTERISK_ARI_PASSWORD, Ollama model, etc.)

# 2. Download Piper voice
mkdir -p data/piper-voices
wget -P data/piper-voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json

# 3. Pull Ollama model on the host
ollama pull ministral-3:14b-instruct-2512-q8_0

# 4. Start the stack
docker compose up -d

# 5. Check health
curl http://localhost:8083/health        # Dashboard
curl http://localhost:5150/health        # Piper TTS
```

## Services & Ports

| Service | Port | Health check |
|---------|------|--------------|
| `sip-bridge` | 5003 / AudioSocket 9093 | `curl localhost:5003/health` |
| `piper` | 5150 | `curl localhost:5150/health` |
| `async-worker` | 8087 | `curl localhost:8087/health` |
| `dashboard` | 8083 | `curl localhost:8083/health` |
| `whisper-gpu` | 8091 | `curl localhost:8091/health` (only `--profile standalone`) |
| `asterisk` | 5060/8088 | (only `--profile standalone`) |

## Configure company data

After starting, open the dashboard: `http://localhost:8083`

Login: `admin@anrufwerker.local` / `anrufwerker-start` → **change password immediately**

Under **Settings → Company Data**, fill in:
- Company name, owner, callback number
- Services, opening hours
- Greeting text

Alternatively as a JSON file (example: `docs/tenant.example.json`):
```bash
cp docs/tenant.example.json configs/my-business.json
# Edit the file, then set in .env:
# COMPANY_CONFIG=/app/configs/my-business.json
```

## Test TTS

```bash
# Test Piper directly
curl -s -X POST http://localhost:5150/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Hello, how can I help you?", "voice": "de_DE-thorsten-high"}' \
  --output /tmp/test.wav && aplay /tmp/test.wav
```

## Check Asterisk connectivity

```bash
# Standalone profile starts its own Asterisk
docker compose --profile standalone up -d

# Asterisk CLI
docker exec -it anrufwerker-asterisk asterisk -rvvv

# Show SIP endpoints
docker exec anrufwerker-asterisk asterisk -rx "pjsip show endpoints"

# Test ARI connection
curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD \
  http://localhost:8088/ari/asterisk/info
```

## Logs

```bash
# All services
docker compose logs -f

# Only sip-bridge (call processing)
docker compose logs -f sip-bridge

# Only async-worker (extraction)
docker compose logs -f async-worker
```

## Monitoring (optional)

```bash
docker compose --profile monitoring up -d
# Grafana: http://localhost:3001  (admin / password from .env GRAFANA_PASSWORD)
# Prometheus: http://localhost:9092
```

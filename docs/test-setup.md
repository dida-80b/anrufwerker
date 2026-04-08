# Setup & Test

## Quickstart ab Clone

```bash
git clone git@github.com:dida-80b/anrufwerker.git
cd anrufwerker

# 1. Konfiguration
cp .env.example .env
# .env öffnen und Pflichtfelder ausfüllen (ASTERISK_ARI_PASSWORD, FRITZBOX_SIP_PASSWORD, OLLAMA_MODEL)

# 2. Piper-Stimme herunterladen
mkdir -p data/piper-voices
wget -P data/piper-voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json

# 3. Ollama-Modell auf dem Host laden
ollama pull ministral-3:14b-instruct-2512-q8_0

# 4. Stack starten
docker compose up -d

# 5. Health prüfen
curl http://localhost:8083/health        # Dashboard
curl http://localhost:5150/health        # Piper TTS
```

## Services & Ports

| Service | Port | Health-Check |
|---------|------|--------------|
| `sip-bridge` | 5003 / AudioSocket 9093 | `curl localhost:5003/health` |
| `piper` | 5150 | `curl localhost:5150/health` |
| `async-worker` | 8087 | `curl localhost:8087/health` |
| `dashboard` | 8083 | `curl localhost:8083/health` |
| `whisper-gpu` | 8091 | `curl localhost:8091/health` (nur `--profile standalone`) |
| `asterisk` | 5060/8088 | (nur `--profile standalone`) |

## Firmendaten konfigurieren

Nach dem Start Dashboard öffnen: `http://localhost:8083`

Login: `admin@anrufwerker.local` / `anrufwerker-start` → **sofort Passwort ändern**

Unter **Einstellungen → Firmendaten** ausfüllen:
- Firmenname, Inhaber, Rückruf-Nummer
- Dienstleistungen, Öffnungszeiten
- Begrüßungstext

Alternativ als JSON-Datei (Beispiel: `docs/tenant.example.json`):
```bash
cp docs/tenant.example.json configs/mein-betrieb.json
# Datei anpassen, dann in .env:
# COMPANY_CONFIG=/app/configs/mein-betrieb.json
```

## TTS testen

```bash
# Piper direkt testen
curl -s -X POST http://localhost:5150/synthesize \
  -H "Content-Type: application/json" \
  -d '{"text": "Guten Tag, wie kann ich Ihnen helfen?", "voice": "de_DE-thorsten-high"}' \
  --output /tmp/test.wav && aplay /tmp/test.wav
```

## Asterisk-Anbindung prüfen

```bash
# Standalone-Profil startet eigenen Asterisk
docker compose --profile standalone up -d

# Asterisk CLI
docker exec -it anrufwerker-asterisk asterisk -rvvv

# SIP-Endpoints anzeigen
docker exec anrufwerker-asterisk asterisk -rx "pjsip show endpoints"

# ARI-Verbindung testen
curl -u $ASTERISK_ARI_USER:$ASTERISK_ARI_PASSWORD \
  http://localhost:8088/ari/asterisk/info
```

## Logs

```bash
# Alle Services
docker compose logs -f

# Nur sip-bridge (Anruf-Verarbeitung)
docker compose logs -f sip-bridge

# Nur async-worker (Extraktion)
docker compose logs -f async-worker
```

## Monitoring (optional)

```bash
docker compose --profile monitoring up -d
# Grafana: http://localhost:3001  (admin / Passwort aus .env GRAFANA_PASSWORD)
# Prometheus: http://localhost:9092
```

# anrufwerker

KI-basierter Telefonassistent für kleine Unternehmen — Handwerker, Praxen, Dienstleister.

Nimmt Anrufe entgegen, erkennt Anliegen, antwortet in Echtzeit und schreibt Aufgaben in eine Queue zur Nachbearbeitung. Läuft vollständig lokal, keine Cloud erforderlich.

---

## Was der Stack macht

```
Anrufer → Asterisk → SIP-Bridge → Whisper (STT) → Ollama (LLM) → Piper (TTS) → Anrufer
                                         ↓
                                   Async-Worker
                                   (Extraktion, Queue)
                                         ↓
                                   Dashboard (Admin-UI)
```

- **STT:** [whisper.cpp](https://github.com/ggerganov/whisper.cpp) via HTTP (Vulkan/ROCm/CUDA)
- **LLM:** [Ollama](https://ollama.com) auf dem Host (kein Container nötig)
- **TTS:** [Piper](https://github.com/rhasspy/piper) (lokal, ONNX) oder edge-tts (Microsoft Azure Neural, online)
- **Telefonie:** Asterisk mit AudioSocket-Protokoll

---

## Voraussetzungen

- Docker & Docker Compose
- Ollama auf dem Host (`http://127.0.0.1:11434`)
- Asterisk (lokal oder als Container mit `--profile standalone`)
- Whisper-Modell: `ggml-large-v3-turbo.bin` (oder kleineres)
- GPU empfohlen für Whisper (ROCm / Vulkan / CUDA)

---

## Quickstart

```bash
# 1. Repository klonen
git clone https://github.com/dein-user/anrufwerker.git
cd anrufwerker

# 2. Environment konfigurieren
cp .env.example .env
# .env anpassen: Asterisk-Zugangsdaten, Ollama-Modell, Piper-Voice

# 3. LLM-Modell auf dem Host laden
ollama pull qwen2.5:7b

# 4. Piper-Voices herunterladen (Beispiel: Thorsten Deutsch)
mkdir -p data/piper-voices
wget -P data/piper-voices \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx \
  https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/high/de_DE-thorsten-high.onnx.json

# 5. Stack starten
docker compose up -d

# 6. Health prüfen
curl http://localhost:8083/health   # Dashboard
```

### Mit eigenem Asterisk + Whisper (standalone)

```bash
docker compose --profile standalone up -d
```

---

## Services & Ports

| Service | Port | Beschreibung |
|---------|------|--------------|
| `sip-bridge` | 5003 / AudioSocket 9093 | Asterisk AudioSocket + TTS/STT/LLM |
| `piper` | 5150 | Piper TTS HTTP-Service |
| `async-worker` | 8087 | Job-Queue Prozessor |
| `dashboard` | 8083 | Admin-UI |
| `whisper-gpu` | 8091 | Whisper STT (Profil: `standalone`) |
| `asterisk` | 5060/8088 | PBX (Profil: `standalone`) |

---

## Konfiguration

### TTS-Engine

Standard ist Piper (lokal, kein Internet):

```env
TTS_ENGINE=piper
PIPER_VOICE=de_DE-thorsten-high
PIPER_URL=http://127.0.0.1:5150
```

Alternativ edge-tts (Microsoft Azure Neural, benötigt Internet):

```env
TTS_ENGINE=edge
TTS_VOICE=de-DE-SeraphinaMultilingualNeural
```

### Wichtige Variablen

| Variable | Beschreibung | Default |
|----------|--------------|---------|
| `TTS_ENGINE` | TTS-Engine (`piper` oder `edge`) | `piper` |
| `PIPER_VOICE` | Piper-Stimme | `de_DE-thorsten-high` |
| `OLLAMA_URL` | Ollama-Adresse | `http://host.docker.internal:11434/api/chat` |
| `OLLAMA_MODEL` | LLM-Modell | `qwen2.5:7b` |
| `WHISPER_URL` | Whisper HTTP-Endpunkt | `http://127.0.0.1:8090` |
| `STT_ENGINE` | STT-Engine | `whisper-http` |
| `INBOUND_ENABLED` | Eingehende Anrufe aktivieren | `true` |

Vollständige Referenz: `.env.example`

### Firmenkonfiguration

Betriebsdaten (Name, Dienstleistungen, Öffnungszeiten, etc.) werden im Admin-Dashboard unter **Einstellungen → Firmendaten** gepflegt — keine JSON-Datei nötig.

Alternativ als Datei: Beispiel unter `docs/tenant.example.json`.

---

## Admin-Dashboard

Erreichbar unter `http://localhost:8083`

Standard-Login:
- E-Mail: `admin@anrufwerker.local`
- Passwort: `anrufwerker-start`

Sofort nach dem ersten Login ändern unter **Account → Passwort**.

---

## Piper-Stimmen (Deutsch)

Empfohlene deutsche Stimmen:

| Stimme | Qualität | Größe |
|--------|----------|-------|
| `de_DE-thorsten-high` | Hoch | ~109 MB |
| `de_DE-thorsten_emotional-medium` | Mittel | ~74 MB |
| `de_DE-kerstin-low` | Niedrig (schnell) | ~61 MB |
| `de_DE-ramona-low` | Niedrig (schnell) | ~61 MB |

Alle Piper-Stimmen: [rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)

---

## Monitoring (optional)

```bash
docker compose --profile monitoring up -d
```

- Prometheus: `http://localhost:9092`
- Grafana: `http://localhost:3001` (Standard-Passwort: `admin`)

---

## Datenschutz

- Anrufdaten werden lokal in `data/transcripts/` gespeichert
- Keine Weitergabe an externe Dienste (außer bei `TTS_ENGINE=edge`)
- `data/transcripts/` und Datenbanken sind in `.gitignore` ausgeschlossen

---

## Lizenz

MIT

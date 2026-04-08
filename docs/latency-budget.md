# anrufwerker - Latency Budget

## Ziel

> Budget gilt primär für **Inbound Live-Calls**. Outbound kann eigenes Budget/Fallbacks haben, da es meist nicht vom aktiven Anruferdruck abhängt.


**Maximale Antwortzeit im Live-Call: 2-3 Sekunden**

Dieses Dokument definiert das Latenz-Budget für alle Komponenten im Live-Call-Pfad.

---

## Latency Breakdown

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Latency Budget                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Caller spricht ──────────────────────────────────────────────────▶  │
│  │                                                                    │
│  ▼                                                                    │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────┐  │
│  │ Audio Buffer│   │    STT      │   │    LLM      │   │   TTS   │  │
│  │  (300ms)    │──▶│  (800ms)    │──▶│  (800ms)    │──▶│ (400ms) │  │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────┘  │
│       300ms            800ms             800ms            400ms     │
│  ════════════════════════════════════════════════════════════════   │
│  TOTAL: 2300ms (Ziel: < 3000ms)                                        │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## Komponenten-Details

### 1. Audio Buffer / VAD (300ms)

| Parameter | Wert |
|-----------|------|
| Buffer Size | 100-300ms |
| VAD Latency | ~50ms |
| Network Jitter | +150ms (Puffer) |

**Optimierung**: 
- Adaptive Buffering basierend auf Netzwerkqualität
- Bei guter Verbindung: 100ms Buffer
- Bei schlechter Verbindung: 300ms Buffer

### 2. STT - Speech-to-Text (800ms)

| Modell | Latenz (approx) |
|--------|-----------------|
| Faster-Whisper (base) | 500-800ms |
| Faster-Whisper (small) | 300-500ms |
| Whisper.cpp | 600-1000ms |

**Budget**: 800ms

**Optimierung**:
- `faster-whisper` mit small/base Modell
- Batch-Processing bei längeren Segmenten
- Streaming-Modus nutzen

### 3. LLM - Intent + Response (800ms)

| Modell | Latenz (approx) |
|--------|-----------------|
| qwen3.5:9b (Q4) | 600-1200ms |
| qwen3.5:9b (Q4) | 400-800ms |
| mistral:7b | 700-1500ms |

**Budget**: 800ms

**Optimierung**:
- `qwen3.5:9b` für schnelle Antworten
- Prompt-Engineering für kurze Outputs
- Keine externen API-Calls (lokales Modell)
- Max Tokens: 50-100 (nicht mehr)

### 4. TTS - Text-to-Speech (400ms)

| Modell | Latenz (approx) |
|--------|-----------------|
| Silero (ONNX) | 100-200ms |
| eSpeak-ng | 50-100ms |
| Coqui | 300-500ms |

**Budget**: 400ms

**Optimierung**:
- Silero mit ONNX-Runtime
- Pre-generierte Audio-Fragmente für Standard-Antworten
- Streaming-TTS wenn verfügbar

---

## Worst-Case Szenario

| Szenario | Latenz | Gesamt |
|----------|--------|--------|
| Normal | 2300ms | OK |
| Schlechtes Netz | +500ms | 2800ms |
| Langsames Modell | +500ms | 2800ms |
| Beides | +1000ms | 3300ms |

**Falls Latenz überschritten**:
1. Timeout mittwort (" Standard-AnEinen Moment bitte...")
2. Caller auf Warteschlange
3. Fallback auf Mensch (Transfer)

---

## Async-Path (kein Live-Budget)

Folgende Operationen sind NICHT im Live-Latenz-Budget:

- Kontaktsuche
- Kalender-Abfrage
- CRM-Update
- E-Mail/SMS-Versand
- Transcripts-Speicherung

Diese laufen im **Async Worker** nach Call-Ende.

---

## Monitoring

**Metriken**:

```prometheus
# Latenz pro Komponente
latency_stt_seconds_bucket{le="1"}
latency_llm_seconds_bucket{le="1"}
latency_tts_seconds_bucket{0.5"}

# End-to-End
latency_total_seconds_bucket{le="3"}
```

**Alerts**:
- > 3s: Warning
- > 5s: Critical

---

## Tuning-Knobs

| ENV | Beschreibung | Default |
|-----|--------------|---------|
| `STT_MODEL` | STT-Modell | `small` |
| `LLM_MODEL` | LLM-Modell | `qwen3.5:9b` |
| `LLM_MAX_TOKENS` | Max Tokens für Response | `80` |
| `TTS_MODEL` | TTS-Modell | `silero` |
| `AUDIO_BUFFER_MS` | Audio Buffer | `200` |

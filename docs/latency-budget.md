# anrufwerker - Latency Budget

## Goal

> This budget applies primarily to **inbound live calls**. Outbound calls can have their own budget / fallbacks since they are not subject to active caller pressure.

**Maximum response time on a live call: 2–3 seconds**

This document defines the latency budget for all components in the live-call path.

---

## Latency breakdown

```
┌────────────────────────────────────────────────────────────────────────┐
│                         Latency Budget                                  │
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  Caller speaks ───────────────────────────────────────────────────▶  │
│  │                                                                    │
│  ▼                                                                    │
│  ┌─────────────┐   ┌─────────────┐   ┌─────────────┐   ┌─────────┐  │
│  │ Audio Buffer│   │    STT      │   │    LLM      │   │   TTS   │  │
│  │  (300ms)    │──▶│  (800ms)    │──▶│  (800ms)    │──▶│ (400ms) │  │
│  └─────────────┘   └─────────────┘   └─────────────┘   └─────────┘  │
│       300ms            800ms             800ms            400ms     │
│  ════════════════════════════════════════════════════════════════   │
│  TOTAL: 2300ms (target: < 3000ms)                                      │
│                                                                        │
└────────────────────────────────────────────────────────────────────────┘
```

## Component details

### 1. Audio buffer / VAD (300ms)

| Parameter | Value |
|-----------|-------|
| Buffer size | 100–300ms |
| VAD latency | ~50ms |
| Network jitter | +150ms (buffer) |

**Optimisation**:
- Adaptive buffering based on network quality
- Good connection: 100ms buffer
- Poor connection: 300ms buffer

### 2. STT — speech-to-text (800ms)

| Model | Latency (approx) |
|-------|-----------------|
| Faster-Whisper (base) | 500–800ms |
| Faster-Whisper (small) | 300–500ms |
| Whisper.cpp | 600–1000ms |

**Budget**: 800ms

**Optimisation**:
- `faster-whisper` with small/base model
- Batch processing for longer segments
- Use streaming mode

### 3. LLM — intent + response (800ms)

| Model | Latency (approx) |
|-------|-----------------|
| ministral-3:14b-instruct-2512-q8_0 (Q8) | 600–1200ms |
| ministral-3:14b-instruct-2512-q8_0 (Q4) | 400–800ms |
| mistral:7b | 700–1500ms |

**Budget**: 800ms

**Optimisation**:
- `ministral-3:14b-instruct-2512-q8_0` for fast responses
- Prompt engineering for short outputs
- No external API calls (local model)
- Max tokens: 50–100 (no more)

### 4. TTS — text-to-speech (400ms)

| Model | Latency (approx) |
|-------|-----------------|
| Piper (ONNX) | 100–300ms |
| Edge TTS (online) | 300–600ms |

**Budget**: 400ms

**Optimisation**:
- Piper with ONNX runtime
- Pre-generated audio fragments for standard responses
- Streaming TTS where available

---

## Worst-case scenarios

| Scenario | Latency | Total |
|----------|---------|-------|
| Normal | 2300ms | OK |
| Poor network | +500ms | 2800ms |
| Slow model | +500ms | 2800ms |
| Both | +1000ms | 3300ms |

**If latency is exceeded**:
1. Timeout response ("One moment please...")
2. Caller placed in queue
3. Fallback to human (transfer)

---

## Async path (no live budget)

The following operations are NOT in the live latency budget:

- Contact search
- Calendar query
- CRM update
- Email / SMS send
- Transcript storage

These run in the **async worker** after the call ends.

---

## Monitoring

**Metrics**:

```prometheus
# Latency per component
latency_stt_seconds_bucket{le="1"}
latency_llm_seconds_bucket{le="1"}
latency_tts_seconds_bucket{le="0.5"}

# End-to-end
latency_total_seconds_bucket{le="3"}
```

**Alerts**:
- > 3s: Warning
- > 5s: Critical

---

## Tuning knobs

| ENV | Description | Default |
|-----|-------------|---------|
| `FAST_STT_MODEL` | Whisper model | `small` |
| `OLLAMA_MODEL` | LLM model | `ministral-3:14b-instruct-2512-q8_0` |
| `OLLAMA_NUM_PREDICT` | Max tokens for response | `80` |
| `PIPER_VOICE` | Piper voice | `de_DE-thorsten-high` |
| `VAD_SILENCE_FRAMES_TO_END` | Silence frames until turn ends | `12` |

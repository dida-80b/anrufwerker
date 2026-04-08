# anrufwerker - Architektur

## Übersicht

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          anrufwerker System                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐   │
│  │  Asterisk    │────▶│  sip-bridge  │────▶│  TTS (Antwort)       │   │
│  │  / Fritzbox  │     │  (STT+LLM)   │     │  (Piper TTS)         │   │
│  └──────────────┘     └──────┬───────┘     └──────────────────────┘   │
│                               │                                          │
│                               ▼                                          │
│                      ┌──────────────────┐                               │
│                      │  Queue (SQLite)  │                               │
│                      │  call_id + data  │                               │
│                      └────────┬─────────┘                               │
│                               │                                          │
│                               ▼                                          │
│                      ┌──────────────────┐                               │
│                      │  Async Worker    │                               │
│                      │  (Kontakte/Cal)  │                               │
│                      └──────────────────┘                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Komponenten

### 1. Telefon-Gateway (External)

- **Asterisk**: Klassische Telefonanlage, SIP-Trunk
- **Fritzbox**: Consumer-Router mit Telefonie, CAPI over network
- Anbindung via SIP/RTP oder Fritzbox CAPI

### 2. sip-bridge (Core Service)

**Verantwortung**: Echtzeit-Verarbeitung während des Anrufs

**Aufgaben**:
- STT (Speech-to-Text): Whisper HTTP (whisper.cpp)
- Intent/Slot Extraction: Lokales LLM via Ollama (qwen2.5:7b)
- Response Generation: Kontextbezogene Antwort
- TTS: Piper (lokal) oder Edge TTS (online)

**Anforderungen**:
- Latenz: < 3s Ende-zu-Ende
- Keine externen API-Calls während des Anrufs
- State-Machine für Call-Flow

**Technologie**: Python/FastAPI, Host-Ollama für LLM (kein Ollama-Container im Stack)

### 3. Queue (Repository Pattern)

**Interface**:
```python
class QueueRepository(Protocol):
    def enqueue(call_id: str, payload: dict) -> None: ...
    def dequeue() -> tuple[str, dict] | None: ...
    def mark_completed(call_id: str) -> None: ...
    def is_processed(call_id) -> bool: ...
```

**Implementierungen**:
- `SqliteQueueRepository`: Für MVP, SQLite-basiert
- `RedisQueueRepository`: Für Produktion (später)
- `PostgresQueueRepository`: Für Produktion (später)

### 4. Async Worker

**Verantwortung**: Nachgelagerte Verarbeitung

**Aufgaben**:
- Kontaktsuche/erstellung
- Kalender-Terminanfragen
- CRM-Updates
- E-Mail/SMS-Benachrichtigungen
- Transcripts speichern

**Features**:
- Idempotenz-Key: call_id
- Retry-Policy mit Exponential Backoff
- Dead-Letter-Queue für fehlgeschlagene Jobs

### 5. Storage (PostgreSQL, optional)

- Tenant-Konfigurationen
- Transcripts und Call-Logs
- Trainingsdaten-Asset

## API Contract: Live-Engine → Worker

```json
{
  "call_id": "uuid-v4",
  "tenant_id": "string",
  "caller_number": "+49...",
  "timestamp_start": "ISO8601",
  "timestamp_end": "ISO8601",
  "intent": {
    "name": "appointment_request|inquiry|complaint|transfer",
    "confidence": 0.95,
    "slots": {
      "service_type": "string",
      "desired_date": "YYYY-MM-DD",
      "desired_time": "HH:MM",
      "caller_name": "string",
      "caller_phone": "string"
    }
  },
  "transcript": [
    {"role": "user|assistant", "text": "...", "timestamp": "ISO8601"}
  ],
  "summary": "string (optional)",
  "action_required": "none|callback|appointment|transfer",
  "idempotency_key": "call_id"
}
```

## Adapter-Interface für Externe Systeme

```python
class ContactAdapter(Protocol):
    def search(query: str) -> list[Contact]: ...
    def create(contact: Contact) -> str: ...

class CalendarAdapter(Protocol):
    def get_free_slots(date: str) -> list[Slot]: ...
    def request_appointment(slot: Slot) -> str: ...

class CrmAdapter(Protocol):
    def log_interaction(data: dict) -> None: ...
```

**Implementierungen**:
- OpenClaw-Adapter (wenn verfügbar)
- CardDAV für Kontakte
- CalDAV für Kalender
- Custom REST-APIs

## Datenfluss

### Live-Path (während des Anrufs)

```
1. Anruf kommt rein (Asterisk/Fritzbox)
2. SIP Invite → sip-bridge
3. Audio → STT → Transcript
4. Transcript → Intent Detection (LLM)
5. Slots extrahieren
6. Kurze Antwort generieren (LLM)
7. TTS → Audio → Caller
8. Call beenden
9. Daten in Queue schreiben
```

### Async-Path (nach dem Anruf)

```
1. Worker dequeue Job
2. Idempotenz-Check (call_id bereits verarbeitet?)
3. Kontakt suchen/erstellen
4. Kalender-Slots prüfen (wenn Termin gewünscht)
5. CRM-Log schreiben
6. Callback/E-Mail planen (wenn erforderlich)
7. Transcript speichern
8. Job als completed markieren
```

## Sicherheit

- **Keine Secrets in Code**: Alles über env vars
- **TLS**: Alle Verbindungen verschlüsselt
- **WAF**: Rate-Limiting, Input-Validation
- **Audit-Log**: Alle API-Calls geloggt

## Betriebsmodi

### Mode A: Standalone (ohne OpenClaw)

- Direkte Anbindung an Asterisk/Fritzbox
- Lokale Konfiguration (JSON)
- SQLite Queue

### Mode B: Mit OpenClaw

- OpenClaw als Orchestrator
- Adapter für Contacts/Calendar via OpenClaw
- Shared Queue (Redis/Postgres)

Umschaltung via `OPENCLAW_ENABLED=true/false` env var.


### 6. outbound-orchestrator (optional)

**Verantwortung**: Kontrollierte ausgehende Anrufe auf Basis expliziter Missionen.

**Aufgaben**:
- Mission validieren (Policy, Zeitfenster, Rate-Limits)
- Outbound-Call starten (Asterisk)
- Gesprächsergebnis als `direction=outbound` in Queue schreiben

**Wichtig**: Keine autonomen Outbound-Kampagnen ohne explizite Freigabe.

### Outbound-Path (optional)

```
1. API bekommt Mission (to + task)
2. Outbound-Policy prüft Erlaubnis
3. Asterisk startet Anruf
4. sip-bridge führt kurzen mission-basierten Dialog
5. Ergebnis -> Queue (direction=outbound)
6. Async Worker verarbeitet Follow-up
```

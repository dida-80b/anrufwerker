# anrufwerker - Architecture

## Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          anrufwerker System                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐   │
│  │  Asterisk    │────▶│  sip-bridge  │────▶│  TTS (response)      │   │
│  │  / SIP trunk │     │  (STT+LLM)   │     │  (Piper TTS)         │   │
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
│                      │  (contacts/cal)  │                               │
│                      └──────────────────┘                               │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Telephony gateway (external)

- **Asterisk**: classic PBX, SIP trunk
- **Fritz!Box**: consumer router with telephony (one tested option — any SIP trunk works)
- Connection via SIP/RTP or any SIP provider that forwards calls to Asterisk ARI

### 2. sip-bridge (core service)

**Responsibility**: real-time processing during the call

**Tasks**:
- STT (speech-to-text): Whisper HTTP (whisper.cpp)
- Intent/slot extraction: local LLM via Ollama (ministral-3:14b-instruct-2512-q8_0)
- Response generation: context-aware reply
- TTS: Piper (local) or Edge TTS (online)

**Requirements**:
- Latency: < 3s end-to-end
- No external API calls during the call
- State machine for call flow

**Technology**: Python/FastAPI, host Ollama for LLM (no Ollama container in the stack)

### 3. Queue (repository pattern)

**Interface**:
```python
class QueueRepository(Protocol):
    def enqueue(call_id: str, payload: dict) -> None: ...
    def dequeue() -> tuple[str, dict] | None: ...
    def mark_completed(call_id: str) -> None: ...
    def is_processed(call_id) -> bool: ...
```

**Implementations**:
- `SqliteQueueRepository`: for MVP, SQLite-based
- `RedisQueueRepository`: for production (future)
- `PostgresQueueRepository`: for production (future)

### 4. Async worker

**Responsibility**: post-call processing

**Tasks**:
- Contact search / creation
- Calendar appointment requests
- CRM updates
- Email / SMS notifications
- Transcript storage

**Features**:
- Idempotency key: call_id
- Retry policy with exponential backoff
- Dead-letter queue for failed jobs

### 5. Storage (PostgreSQL, optional)

- Tenant configurations
- Transcripts and call logs
- Training data asset

## API contract: live engine → worker

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

## Adapter interface for external systems

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

**Implementations**:
- OpenClaw adapter (if available)
- CardDAV for contacts
- CalDAV for calendar
- Custom REST APIs

## Data flow

### Live path (during the call)

```
1. Call arrives (Asterisk / SIP trunk)
2. SIP Invite → sip-bridge
3. Audio → STT → transcript
4. Transcript → intent detection (LLM)
5. Extract slots
6. Generate short reply (LLM)
7. TTS → audio → caller
8. End call
9. Write data to queue
```

### Async path (after the call)

```
1. Worker dequeues job
2. Idempotency check (call_id already processed?)
3. Search / create contact
4. Check calendar slots (if appointment requested)
5. Write CRM log
6. Schedule callback / email (if required)
7. Save transcript
8. Mark job as completed
```

## Security

- **No secrets in code**: everything via env vars
- **TLS**: all connections encrypted
- **WAF**: rate limiting, input validation
- **Audit log**: all API calls logged

## Operating modes

### Mode A: Standalone (without OpenClaw)

- Direct connection to Asterisk / SIP trunk
- Local configuration (JSON)
- SQLite queue

### Mode B: With OpenClaw

- OpenClaw as orchestrator
- Adapters for contacts / calendar via OpenClaw
- Shared queue (Redis / Postgres)

Switch via `OPENCLAW_ENABLED=true/false` env var.


### 6. outbound-orchestrator (optional)

**Responsibility**: controlled outbound calls based on explicit missions.

**Tasks**:
- Validate mission (policy, time windows, rate limits)
- Originate outbound call (Asterisk)
- Write call result as `direction=outbound` to queue

**Important**: no autonomous outbound campaigns without explicit approval.

### Outbound path (optional)

```
1. API receives mission (to + task)
2. Outbound policy checks permission
3. Asterisk originates call
4. sip-bridge conducts short mission-based dialogue
5. Result → queue (direction=outbound)
6. Async worker processes follow-up
```

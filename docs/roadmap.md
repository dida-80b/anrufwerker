# anrufwerker - Roadmap

## Phase overview

| Phase | Timeline | Focus | Milestone |
|-------|----------|-------|-----------|
| MVP | 4–6 weeks | Core functionality | First test call |
| Pilot | 8–12 weeks | First customers | 3–5 pilots |
| Product | Ongoing | Scaling | Market entry |

---

## Phase 1: MVP (Minimum Viable Product)

### Goal
Working demo system with baseline capabilities.

### Scope

- [ ] Asterisk integration (SIP/RTP)
- [ ] STT (Faster-Whisper)
- [ ] Intent detection (ministral-3:14b-instruct-2512-q8_0 via host Ollama)
- [ ] Generate short text responses
- [ ] TTS (Piper)
- [ ] SQLite queue
- [ ] Async worker for contact log
- [ ] Basic configuration via JSON/env
- [ ] Outbound PoC (mission-based confirmation call, optional)

### Deliverables

- docker-compose.yml with all services
- sip-bridge AudioSocket handler
- Worker job processing
- Tenant configuration (JSON)
- Transcript storage

### Test criteria

- Call is answered and replied to
- Intent correctly detected (>80% on clear requests)
- Latency < 5s (target: <3s)
- No runtime crashes

---

## Phase 2: Pilot

### Goal
Real customer pilots in the trades sector.

### Scope

- [ ] SIP trunk integrations (Fritz!Box, Sipgate, Telekom, etc.)
- [ ] CardDAV adapter for contacts
- [ ] CalDAV adapter for calendar
- [ ] OpenClaw adapter (optional)
- [ ] Outbound orchestrator (rate limit + allowed hours + approval rules)
- [ ] Configurable prompts
- [ ] Logging / dashboard
- [ ] Retry mechanisms in worker

### Deliverables

- Adapter interface documented
- 3–5 pilots with live system
- Feedback loop implemented
- First training data collected

### Test criteria

- 95% uptime
- < 3s average response time
- Pilots satisfied (NPS > 7)

---

## Phase 3: Product

### Goal
Market-ready product for tradespeople and small businesses.

### Scope

- [ ] Redis/Postgres queue (instead of SQLite)
- [ ] Multi-tenancy
- [ ] Web dashboard for admins
- [ ] Audio recording (opt-in)
- [ ] Extended intents (price enquiry, status)
- [ ] CRM integrations
- [ ] SLA monitoring
- [ ] Role / permission system

### Deliverables

- Production installation at 20+ customers
- Support processes
- End-user documentation
- Training data asset (anonymised)

---

## Backlog (future)

- Medical practice module
- Multi-language support (EN, TR, etc.)
- Voicemail detection
- Sentiment analysis
- Call analytics dashboard
- Marketing automation
- WhatsApp / SMS integration

---

## Milestones

| Milestone | Planned | Status |
|-----------|---------|--------|
| Blueprint complete | 2026-03-11 | ✅ |
| MVP code complete | TBD | ⏳ |
| First test call | TBD | ⏳ |
| Pilot deployable | TBD | ℔ |
| Product ready | TBD | ℔ |

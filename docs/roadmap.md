# anrufwerker - Roadmap

## Phasenübersicht

| Phase | Zeitraum | Focus | Meilenstein |
|-------|----------|-------|-------------|
| MVP | 4-6 Wochen | Kernfunktionalität | Erster Testanruf |
| Pilot | 8-12 Wochen | Erste Kunden | 3-5 Piloten |
| Produkt | Ongoing | Skalierung | Markteintritt |

---

## Phase 1: MVP (Minimum Viable Product)

### Ziel
Funktionierender Demo-System mit Basisfähigkeiten.

### Umfang

- [ ] Asterisk-Anbindung (SIP/RTP)
- [ ] STT (Faster-Whisper)
- [ ] Intent Detection (ministral-3:14b-instruct-2512-q8_0 via Host-Ollama)
- [ ] Kurze Text-Antworten generieren
- [ ] TTS (Piper)
- [ ] SQLite Queue
- [ ] Async Worker für Contact-Log
- [ ] Basis-Konfiguration via JSON/env
- [ ] Outbound PoC (mission-basierter Bestätigungsanruf, optional)

### Deliverables

- docker-compose.yml mit allen Services
- sip-bridge AudioSocket-Handler
- Worker-Job-Verarbeitung
- Tenant-Konfiguration (JSON)
- Transcripts-Speicherung

### Testkriterien

- Anruf wird angenommen und beantwortet
- Intent wird korrekt erkannt (>80% bei klaren Anfragen)
- Latenz < 5s (Ziel: <3s)
- Keine Runtime-Crashes

---

## Phase 2: Pilot

### Ziel
Echte Kundenpiloten im Handwerker-Bereich.

### Umfang

- [ ] Fritzbox CAPI-Integration
- [ ] CardDAV-Adapter für Kontakte
- [ ] CalDAV-Adapter für Kalender
- [ ] OpenClaw-Adapter (optional)
- [ ] Outbound-Orchestrator (Rate-Limit + Allowed-Hours + Approval-Regeln)
- [ ] Konfigurierbare Prompts
- [ ] Logging/Dashboard
- [ ] Retry-Mechanismen im Worker

### Deliverables

- Adapter-Interface dokumentiert
- 3-5 Piloten mit Live-System
- Feedback-Loop implementiert
- Erste Trainingsdaten gesammelt

### Testkriterien

- 95% Uptime
- < 3s durchschnittliche Antwortzeit
- Piloten zufrieden (NPS > 7)

---

## Phase 3: Produkt

### Ziel
Marktreifes Produkt für Handwerker.

### Umfang

- [ ] Redis/Postgres Queue (statt SQLite)
- [ ] Multi-Tenantfähigkeit
- [ ] Web-Dashboard für Admins
- [ ] Audio-Recording (opt-in)
- [ ] Erweiterte Intents (Preisanfrage, Status)
- [ ] CRM-Integrationen
- [ ] SLA-Monitoring
- [ ] Rollen/Rechte-System

### Deliverables

- Produktive Installation bei 20+ Kunden
- Support-Prozesse
- Dokumentation für Endkunden
- Trainingsdaten-Asset (anonymisiert)

---

## Backlog (Future)

- Arztpraxen-Modul
- Mehrsprachigkeit (EN, TR, etc.)
- Voicemail-Erkennung
- Sentiment-Analyse
- Call-Analytics Dashboard
- Marketing-Automation
- WhatsApp/SMS-Integration

---

## Meilensteine (Zeitmarken)

| Meilenstein | Geplant | Status |
|-------------|---------|--------|
| Blueprint fertig | 2026-03-11 | ✅ |
| MVP Code complete | TBD | ⏳ |
| Erster Testanruf | TBD | ⏳ |
| Pilot deploybar | TBD | ℔ |
| Produkt ready | TBD | ℔ |

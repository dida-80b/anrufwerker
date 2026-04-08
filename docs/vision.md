# anrufwerker - Vision

## Produktvision

**anrufwerker** ist ein Telefon-Assistent für kleine Unternehmen (Handwerker, Praxen, KMU), der eingehende Anrufe automatisiert annimmt, Kundenanliegen erfasst und weiterverarbeitet.

## Zielgruppe

### Phase 1: Handwerker
- Elektriker, Installateure, Maler, Tischler
- 1-10 Mitarbeiter
- typische Anfragen: Terminvereinbarung, Preisauskunft, Auftragsstatus

### Phase 2: Erweiterungen
- Arztpraxen (Terminvereinbarung, Rezeptanfragen)
- KMU (allgemeine Anfragen, Weiterleitung)

## Leitprinzipien

1. **Niedrige Latenz im Live-Call** - max. 2-3s Antwortzeit
2. **Lokale Modelle** - ministral-3:14b-instruct-2512-q8_0 oder vergleichbar (via Ollama)
3. **Trennung Live/Async** - schnelle Antwort im Call, langsame Operationen nachgelagert
4. **Datensouveränität** - alle Daten in DE, keine US-Cloud
5. **Idempotenz** - jeder Call hat idempotente Verarbeitung via call_id
6. **Optionale Outbound-Automation** - nur kontrolliert, mission-basiert, policy-gesichert

## Was NICHT gemacht wird

- Keine Preiszusagen ohne Bestätigung
- Keine verbindlichen Terminbuchungen ohne Menschliche Bestätigung
- Keine medizinischen Diagnosen
- Keine sensitive Daten ohne explizite Einwilligung

Siehe: `docs/architecture.md` für die Umsetzung.

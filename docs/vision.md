# anrufwerker - Vision

## Product vision

**anrufwerker** is a phone assistant for small businesses (tradespeople, medical practices, SMEs) that automatically answers inbound calls, captures customer requests, and routes them for follow-up.

## Target audience

### Phase 1: Tradespeople
- Electricians, plumbers, painters, carpenters
- 1–10 employees
- Typical requests: appointment booking, price enquiries, job status

### Phase 2: Extensions
- Medical practices (appointment booking, prescription requests)
- SMEs (general enquiries, call routing)

## Guiding principles

1. **Low latency on live calls** — max. 2–3s response time
2. **Local models** — ministral-3:14b-instruct-2512-q8_0 or equivalent (via Ollama)
3. **Separation of live and async** — fast reply in the call, slow operations post-call
4. **Data sovereignty** — all data stored locally, no US cloud
5. **Idempotency** — every call has idempotent processing via call_id
6. **Optional outbound automation** — controlled only, mission-based, policy-protected

## What will NOT be done

- No price commitments without confirmation
- No binding appointment bookings without human confirmation
- No medical diagnoses
- No sensitive data without explicit consent

See: `docs/architecture.md` for the implementation.

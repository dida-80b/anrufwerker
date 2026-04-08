# Contributing

## Scope

This repository contains a local-first telephony stack with Asterisk, STT, TTS, LLM integration and an admin dashboard. Contributions should prefer small, reviewable changes.

## Before You Start

- Open an issue first for larger changes, behavioral changes or architectural work.
- Do not commit secrets, `.env` files, runtime databases, transcripts or recordings.
- Keep deployment defaults conservative and document any new environment variables.

## Development

```bash
cp .env.example .env
pytest -q
docker compose config
```

## Pull Requests

- Keep PRs focused on one concern.
- Include tests or a clear reason why tests are not needed.
- Update docs when ports, env vars, setup steps or runtime behavior change.
- For telephony or workflow changes, describe the expected user-visible behavior.

## Security

If you find a vulnerability, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

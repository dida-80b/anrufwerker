SHELL := /bin/bash

.PHONY: check build up down preflight

check:
	docker compose config

build:
	docker compose build live-engine async-worker

up:
	OUTBOUND_ENABLED=true OUTBOUND_ALLOWED_HOURS=00:00-23:59 ASTERISK_ORIGINATE_ENABLED=false docker compose up -d --no-deps live-engine async-worker

down:
	docker compose down

preflight:
	./scripts/preflight.sh

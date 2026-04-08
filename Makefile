SHELL := /bin/bash

.PHONY: check build up down preflight

check:
	docker compose config

build:
	docker compose build sip-bridge piper async-worker

up:
	docker compose up -d

down:
	docker compose down

preflight:
	./scripts/preflight.sh

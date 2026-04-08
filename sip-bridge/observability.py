#!/usr/bin/env python3
"""
Small structured logging helpers for timing and state signals.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Dict


def log_event(logger: logging.Logger, event: str, **fields):
    payload = " ".join(f"{key}={value}" for key, value in fields.items())
    if payload:
        logger.info("event=%s %s", event, payload)
    else:
        logger.info("event=%s", event)


@dataclass
class StepTimer:
    logger: logging.Logger
    event: str
    fields: Dict[str, object] = field(default_factory=dict)
    start: float = field(default_factory=time.monotonic)

    def emit(self, **extra_fields):
        merged = dict(self.fields)
        merged.update(extra_fields)
        merged["latency_ms"] = int((time.monotonic() - self.start) * 1000)
        log_event(self.logger, self.event, **merged)


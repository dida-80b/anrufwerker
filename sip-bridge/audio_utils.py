#!/usr/bin/env python3
"""
Shared audio helpers for the AudioSocket flow.
"""

from __future__ import annotations

import os
import struct
import tempfile
import wave


def rms_level(audio_data: bytes) -> float:
    if len(audio_data) < 2:
        return 0.0
    usable = audio_data[: len(audio_data) // 2 * 2]
    if not usable:
        return 0.0
    samples = struct.unpack(f"<{len(usable) // 2}h", usable)
    if not samples:
        return 0.0
    return (sum(sample * sample for sample in samples) / len(samples)) ** 0.5


def is_speech_frame(audio_data: bytes, threshold: int) -> bool:
    return rms_level(audio_data) >= threshold


def slin_to_wav_bytes(
    slin_data: bytes, sample_rate: int, sample_width: int, channels: int
) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        path = handle.name
    try:
        with wave.open(path, "wb") as wav_handle:
            wav_handle.setnchannels(channels)
            wav_handle.setsampwidth(sample_width)
            wav_handle.setframerate(sample_rate)
            wav_handle.writeframes(slin_data)
        with open(path, "rb") as handle:
            return handle.read()
    finally:
        os.unlink(path)


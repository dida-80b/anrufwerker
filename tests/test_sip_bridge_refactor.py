import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SIP_BRIDGE_DIR = REPO_ROOT / "sip-bridge"
sys.path.insert(0, str(SIP_BRIDGE_DIR))

from audio_utils import is_speech_frame, rms_level, slin_to_wav_bytes
from stt_providers import build_stt_registry, get_stt_provider
from tts_providers import build_tts_registry


def test_tts_registry_contains_supported_engines():
    registry = build_tts_registry(piper_url="http://127.0.0.1:5150", piper_voice="de_DE-thorsten-high")
    assert {"piper", "edge"} <= set(registry)


def test_stt_registry_defaults_to_whisper_http():
    registry = build_stt_registry("http://127.0.0.1:8090")
    assert "whisper-http" in registry
    provider = get_stt_provider("http://127.0.0.1:8090")
    assert provider.name == "whisper-http"


def test_audio_utils_compute_rms_and_threshold():
    loud_frame = (1000).to_bytes(2, "little", signed=True) * 160
    quiet_frame = (10).to_bytes(2, "little", signed=True) * 160
    assert rms_level(loud_frame) > rms_level(quiet_frame)
    assert is_speech_frame(loud_frame, threshold=200)
    assert not is_speech_frame(quiet_frame, threshold=200)


def test_slin_to_wav_bytes_produces_riff_header():
    slin_data = (500).to_bytes(2, "little", signed=True) * 160
    wav_bytes = slin_to_wav_bytes(slin_data, sample_rate=8000, sample_width=2, channels=1)
    assert wav_bytes[:4] == b"RIFF"
    assert b"WAVE" in wav_bytes[:16]

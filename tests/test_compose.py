from pathlib import Path

import yaml

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_compose_has_required_services():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose.get("services", {})
    assert "sip-bridge" in services
    assert "async-worker" in services
    assert "piper" in services


def test_compose_no_ollama_service():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose.get("services", {})
    assert "ollama" not in services, "Ollama should run on host, not in compose"


def test_compose_no_kokoro_service():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    services = compose.get("services", {})
    assert "kokoro" not in services
    assert "kokoro-german" not in services


def test_sip_bridge_tts_engine_default():
    compose = yaml.safe_load(COMPOSE_FILE.read_text())
    sip_bridge = compose.get("services", {}).get("sip-bridge", {})
    env = {e.split("=", 1)[0]: e.split("=", 1)[1] for e in sip_bridge.get("environment", []) if "=" in e}
    assert "piper" in env.get("TTS_ENGINE", ""), "TTS_ENGINE default should be piper"

"""
Centralized configuration loader.

Reads `config/config.yaml` and the environment (populated from `config/.env`
by python-dotenv in main.py) and exposes a single `SETTINGS` object plus a few
convenience helpers used across the project.
"""
import os
from pathlib import Path
from functools import lru_cache

import yaml

CONFIG_PATH = Path("config") / "config.yaml"

_DEFAULTS = {
    "timeouts": {"request": 10},
    "ports_to_scan": [80, 443, 8080, 8443],
    "llm": {
        "provider": "groq",
        "model": "openai/gpt-oss-120b",
        "temperature": 1,
        "top_p": 1,
        "max_completion_tokens": 2048,
        "reasoning_effort": "medium",
    },
    "xss_payloads": [],
    "sqli_payloads": [],
}


@lru_cache(maxsize=1)
def load() -> dict:
    """Load and cache the YAML configuration merged over sensible defaults."""
    data = dict(_DEFAULTS)
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            loaded = yaml.safe_load(fh) or {}
        for key, value in loaded.items():
            if isinstance(value, dict) and isinstance(data.get(key), dict):
                merged = dict(data[key])
                merged.update(value)
                data[key] = merged
            else:
                data[key] = value
    return data


def llm() -> dict:
    """Return LLM settings, allowing the GROQ_MODEL env var to override the model."""
    cfg = dict(load().get("llm", {}))
    env_model = os.getenv("GROQ_MODEL")
    if env_model:
        cfg["model"] = env_model
    return cfg


def request_timeout() -> int:
    return int(load().get("timeouts", {}).get("request", 10))


def ports_to_scan() -> list[int]:
    return list(load().get("ports_to_scan", [80, 443, 8080, 8443]))


def api_key() -> str | None:
    """Groq API key from the environment (loaded from config/.env)."""
    return os.getenv("GROQ_API_KEY")

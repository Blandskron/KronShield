"""Load typed, immutable settings from YAML and the runtime environment."""

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from domain.budget import BudgetLimits


CONFIG_PATH = Path("config") / "config.yaml"
_MAX_CONFIG_SIZE = 64 * 1024
Port = Annotated[int, Field(ge=1, le=65535)]
ModelName = Annotated[str, StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_./:-]*$")]


class _SettingsLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        mapping = super().construct_mapping(node, deep=deep)
        if len(mapping) != len(node.value):
            raise ValueError("Duplicate YAML configuration key")
        return mapping


class _StrictSettings(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)


class TimeoutSettings(_StrictSettings):
    request: float = Field(default=10.0, gt=0, le=120)


class LLMSettings(_StrictSettings):
    provider: Literal["groq"] = "groq"
    model: ModelName = "openai/gpt-oss-120b"
    temperature: float = Field(default=1.0, ge=0, le=2)
    top_p: float = Field(default=1.0, gt=0, le=1)
    max_completion_tokens: int = Field(default=2048, ge=1, le=65536)
    reasoning_effort: Literal["none", "default", "low", "medium", "high"] = "medium"


class Settings(_StrictSettings):
    timeouts: TimeoutSettings = Field(default_factory=TimeoutSettings)
    ports_to_scan: tuple[Port, ...] = Field(default=(80, 443, 8080, 8443), max_length=256)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    execution: BudgetLimits = Field(default_factory=BudgetLimits)

    @field_validator("ports_to_scan", mode="before")
    @classmethod
    def freeze_yaml_sequence(cls, value):
        return tuple(value) if isinstance(value, list) else value

    @field_validator("ports_to_scan")
    @classmethod
    def unique_ports(cls, ports):
        if len(ports) != len(set(ports)):
            raise ValueError("Scan ports must be unique")
        return ports


@lru_cache(maxsize=1)
def configuration() -> Settings:
    """Read a bounded YAML document and apply defaults to omitted fields."""
    if not CONFIG_PATH.exists():
        return Settings()
    try:
        with CONFIG_PATH.open(encoding="utf-8") as file:
            document = file.read(_MAX_CONFIG_SIZE + 1)
        if len(document) > _MAX_CONFIG_SIZE:
            raise ValueError("YAML configuration exceeds its size limit")
        settings = yaml.load(document, Loader=_SettingsLoader)
    except (UnicodeError, yaml.YAMLError):
        raise ValueError("Invalid YAML configuration") from None
    return Settings.model_validate({} if settings is None else settings)


def load() -> dict:
    """Return a copy in the dictionary form used by the legacy checks."""
    return configuration().model_dump(mode="json")


def llm() -> dict:
    cfg = configuration().llm
    env_model = os.getenv("GROQ_MODEL")
    if env_model:
        cfg = LLMSettings.model_validate({**cfg.model_dump(), "model": env_model})
    return cfg.model_dump()


def request_timeout() -> float:
    return configuration().timeouts.request


def ports_to_scan() -> list[int]:
    return list(configuration().ports_to_scan)


def api_key() -> str | None:
    """Groq API key from the process environment."""
    return os.getenv("GROQ_API_KEY")

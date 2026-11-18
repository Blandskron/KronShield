"""
Groq LLM client wrapper.

Uses the Groq Chat Completions API (OpenAI-compatible) with the
`openai/gpt-oss-120b` model by default. Configuration comes from
`core.settings` (config/config.yaml + environment).
"""
from groq import Groq

from core import settings

_client = None


def init(token: str | None = None):
    """
    Initialize the Groq client.

    Args:
        token: Groq API key. If omitted, falls back to GROQ_API_KEY in the env.

    Raises:
        RuntimeError: if no API key can be resolved.
    """
    global _client
    token = token or settings.api_key()
    if not token:
        raise RuntimeError(
            "No se encontró la API key de Groq. Define GROQ_API_KEY en config/.env"
        )
    _client = Groq(api_key=token)
    return _client


def get_client() -> Groq:
    """Return the initialized client, initializing lazily from the env if needed."""
    if _client is None:
        init()
    return _client


def chat(messages: list[dict], max_tokens: int | None = None) -> str:
    """
    Send a chat completion request to Groq and return the text content.

    Args:
        messages: list of {"role", "content"} dicts.
        max_tokens: optional override for max_completion_tokens.

    Returns:
        The assistant message content (stripped).
    """
    cfg = settings.llm()
    client = get_client()
    response = client.chat.completions.create(
        model=cfg.get("model", "openai/gpt-oss-120b"),
        messages=messages,
        temperature=cfg.get("temperature", 1),
        top_p=cfg.get("top_p", 1),
        max_completion_tokens=max_tokens or cfg.get("max_completion_tokens", 2048),
        reasoning_effort=cfg.get("reasoning_effort", "medium"),
        stream=False,
    )
    return (response.choices[0].message.content or "").strip()

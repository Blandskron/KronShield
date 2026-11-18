"""Prepare encoded parameters offline without accepting a network destination."""

from collections.abc import Sequence
from urllib.parse import urlencode


def encode_probe_query(parameters: Sequence[tuple[str, str]], name: str, value: str) -> str:
    """Replace one parameter or append it, retaining the order of all other pairs."""
    if not name or not name.strip():
        raise ValueError("Expected a nonempty parameter name")
    if sum(key == name for key, _ in parameters) > 1:
        raise ValueError("The probe parameter is ambiguous")
    pairs = [(key, value if key == name else current) for key, current in parameters]
    if not any(key == name for key, _ in pairs):
        pairs.append((name, value))
    return urlencode(pairs)

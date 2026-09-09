from domain.models import Finding
from core import xss


def test_xss_returns_list_on_invalid_url():
    """Testing an unreachable URL must return a list of Finding objects."""
    result = xss.test("http://invalid-url.local.nonexistent")
    assert isinstance(result, list)
    assert all(isinstance(f, Finding) for f in result)

from domain.models import Finding, FindingType
from core import recon


def test_recon_returns_findings_on_invalid_host():
    """An unresolvable host yields a list with an ERROR finding (no exception)."""
    result = recon.run("http://invalid-url.local.nonexistent")
    assert isinstance(result, list)
    assert all(isinstance(f, Finding) for f in result)
    assert any(f.type == FindingType.ERROR for f in result)

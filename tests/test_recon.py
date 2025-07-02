from core import recon

def test_recon_google():
    result = recon.run("https://www.google.com")
    assert isinstance(result, list)
    assert any("status_code" in r for r in result)

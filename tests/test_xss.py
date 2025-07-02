from core import xss

def test_xss_invalid_url():
    result = xss.test("http://invalid-url.local")
    assert isinstance(result, list)

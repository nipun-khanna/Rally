import socket

import pytest

from app.browser.url_policy import validate_public_url


def _answers(*addresses):
    return lambda host, port, type=0: [
        (socket.AF_INET6 if ":" in address else socket.AF_INET, socket.SOCK_STREAM,
         6, "", (address, port, 0, 0) if ":" in address else (address, port))
        for address in addresses
    ]


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com", "http://user:pass@example.com",
    "http://localhost", "http://service.local", "http://example.com:8080",
    "http://127.0.0.1", "http://[::1]", "http://169.254.1.2",
])
def test_rejects_non_public_or_unsupported_urls(url):
    with pytest.raises(ValueError):
        validate_public_url(url)


def test_accepts_public_http_url_and_removes_fragment():
    assert validate_public_url("https://example.com/path?q=1#section", _answers("93.184.216.34")) == \
        "https://example.com/path?q=1"


def test_rejects_mixed_public_and_private_dns_answers():
    with pytest.raises(ValueError):
        validate_public_url("https://example.com", _answers("93.184.216.34", "10.0.0.1"))


def test_rejects_dns_failure():
    def fail(*args, **kwargs):
        raise socket.gaierror("no answer")
    with pytest.raises(ValueError):
        validate_public_url("https://example.com", fail)

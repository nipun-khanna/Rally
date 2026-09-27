"""Strict public HTTP URL validation for the local browser capability."""

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit


def validate_public_url(value: str, resolver=socket.getaddrinfo) -> str:
    """Canonicalize a public HTTP(S) URL after validating every DNS answer."""
    if not isinstance(value, str) or not value or any(char in value for char in "\\\r\n\t\x00"):
        raise ValueError("Invalid URL")
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        host = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid URL") from exc
    if (scheme not in {"http", "https"} or not host or parsed.username is not None or
            parsed.password is not None or
            (port is not None and port not in {80, 443}) or
            (scheme == "http" and port == 443) or (scheme == "https" and port == 80)):
        raise ValueError("Unsupported URL")
    try:
        address = ipaddress.ip_address(host)
        addresses = [address]
    except ValueError:
        try:
            normalized_host = host.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise ValueError("Invalid hostname") from exc
        if (normalized_host.endswith(".") or "." not in normalized_host or
                normalized_host.endswith((".local", ".localhost", ".internal", ".test"))):
            raise ValueError("Local hostname")
        try:
            answers = resolver(normalized_host, port or (443 if scheme == "https" else 80),
                               type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(answer[4][0].split("%", 1)[0]) for answer in answers]
        except (OSError, ValueError, IndexError, TypeError) as exc:
            raise ValueError("Hostname could not be resolved") from exc
        if not addresses:
            raise ValueError("Hostname has no addresses")
        host = normalized_host
    if any(not address.is_global for address in addresses):
        raise ValueError("URL resolves to a non-public address")
    netloc = f"[{host}]" if ":" in host else host
    if port is not None:
        netloc += f":{port}"
    return urlunsplit((scheme, netloc, parsed.path or "/", parsed.query, ""))

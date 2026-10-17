"""SSRF-safe page fetching for the fetch_url agent tool. The URL comes from
an LLM (which may be steering on attacker-controlled page text), so it must
never reach internal services or cloud metadata endpoints.

Known gap (acceptable for the proof of concept): the hostname is resolved and
checked here, then resolved again by `requests` when it connects, so a DNS
rebinding attacker could swap the answer in between. The fix is to connect to
the validated IP directly; not done yet.
"""

import ipaddress
import socket
from urllib.parse import urljoin, urlparse

import requests

ALLOWED_PORTS = {80, 443}
ALLOWED_CONTENT_TYPES = ("text/html", "text/plain", "application/json")
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 10
MAX_BYTES = 1_000_000
USER_AGENT = "Mozilla/5.0 (compatible; FramewriteAgent/1.0)"


class FetchError(Exception):
    """A message safe to show the model/user."""


def _ip_is_public(raw: str) -> bool:
    ip = ipaddress.ip_address(raw.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_public_url(url: str) -> None:
    """Raises FetchError unless `url` is http(s) on a standard port and every
    address its host resolves to is a public one."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FetchError("Only http and https URLs can be fetched.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise FetchError("Invalid URL.")
    if port not in ALLOWED_PORTS:
        raise FetchError("Only standard web ports (80/443) can be fetched.")
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(parsed.hostname, port, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        raise FetchError("Could not resolve that host.")
    if not addresses or not all(_ip_is_public(a) for a in addresses):
        raise FetchError("That address isn't a public website, so it can't be fetched.")


def safe_get(url: str) -> tuple[str, str, str]:
    """Returns (final_url, text, content_type). Follows up to MAX_REDIRECTS redirects
    manually so every hop is re-validated, reads at most MAX_BYTES, and only
    accepts text-like content types."""
    for _ in range(MAX_REDIRECTS + 1):
        check_public_url(url)
        try:
            response = requests.get(
                url,
                headers={"User-Agent": USER_AGENT},
                timeout=TIMEOUT_SECONDS,
                stream=True,
                allow_redirects=False,
            )
        except requests.RequestException:
            raise FetchError("The request failed or timed out.")
        try:
            if response.is_redirect or response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise FetchError("Redirect without a destination.")
                url = urljoin(url, location)
                continue
            if response.status_code >= 400:
                raise FetchError(f"The site returned HTTP {response.status_code}.")
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise FetchError(f"Unsupported content type: {content_type or 'unknown'}.")
            body = b""
            for chunk in response.iter_content(chunk_size=16384):
                body += chunk
                if len(body) > MAX_BYTES:
                    body = body[:MAX_BYTES]
                    break
            return url, body.decode(response.encoding or "utf-8", errors="replace"), content_type
        finally:
            response.close()
    raise FetchError("Too many redirects.")

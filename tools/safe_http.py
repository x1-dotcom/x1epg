#!/usr/bin/env python3
from __future__ import annotations

import ipaddress
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

UA = "X1-EPG/1.0 (+https://github.com/x1-dotcom/x1epg)"
TRANSIENT_HTTP = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class FetchResult:
    data: bytes
    final_url: str
    content_type: str | None
    status: int


def _is_public_ip(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_https_url(url: str) -> tuple[str, int | None]:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise RuntimeError(f"URL must be absolute HTTPS: {url!r}")
    if parsed.username or parsed.password:
        raise RuntimeError("credentials in source URL are forbidden")
    if parsed.fragment:
        raise RuntimeError("URL fragments are forbidden")
    if parsed.port not in (None, 443):
        raise RuntimeError("non-standard HTTPS ports are forbidden")
    host = parsed.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise RuntimeError("local hostnames are forbidden")
    try:
        literal_ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not _is_public_ip(str(literal_ip)):
            raise RuntimeError("non-public IP literals are forbidden")
    return host, parsed.port


def _assert_public_dns(host: str) -> None:
    try:
        answers = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RuntimeError(f"DNS resolution failed for {host}: {exc}") from exc
    if not answers:
        raise RuntimeError(f"DNS returned no addresses for {host}")
    resolved = {answer[4][0] for answer in answers}
    for address in resolved:
        try:
            public = _is_public_ip(address)
        except ValueError as exc:
            raise RuntimeError(f"invalid DNS address for {host}: {address}") from exc
        if not public:
            raise RuntimeError(f"DNS for {host} resolved to non-public address {address}")


class SameHostHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, original_host: str, max_redirects: int = 3):
        super().__init__()
        self.original_host = original_host
        self.max_redirects = max_redirects
        self.redirect_count = 0

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        self.redirect_count += 1
        if self.redirect_count > self.max_redirects:
            raise RuntimeError("too many redirects")
        absolute = urljoin(req.full_url, newurl)
        host, _ = _validate_https_url(absolute)
        if host != self.original_host:
            raise RuntimeError(f"cross-host redirect blocked: {self.original_host} -> {host}")
        return super().redirect_request(req, fp, code, msg, headers, absolute)


def fetch_bounded_https(
    url: str,
    *,
    max_bytes: int,
    timeout: int = 45,
    accept: str = "*/*",
    allowed_content_types: tuple[str, ...] | None = None,
    retries: int = 1,
    max_redirects: int = 3,
) -> FetchResult:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    original_host, _ = _validate_https_url(url)
    _assert_public_dns(original_host)
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        handler = SameHostHTTPSRedirectHandler(original_host, max_redirects=max_redirects)
        opener = urllib.request.build_opener(handler)
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept})
        try:
            with opener.open(req, timeout=timeout) as resp:
                final_url = resp.geturl()
                final_host, _ = _validate_https_url(final_url)
                if final_host != original_host:
                    raise RuntimeError(f"unexpected final host: {final_host}")
                _assert_public_dns(final_host)

                status = int(getattr(resp, "status", 200) or 200)
                content_type = resp.headers.get_content_type() if resp.headers else None
                if allowed_content_types and content_type not in allowed_content_types:
                    raise RuntimeError(f"unexpected Content-Type {content_type!r} from {final_url}")

                declared = resp.headers.get("Content-Length") if resp.headers else None
                if declared:
                    try:
                        declared_size = int(declared)
                    except ValueError:
                        raise RuntimeError("invalid Content-Length header")
                    if declared_size < 0 or declared_size > max_bytes:
                        raise RuntimeError("declared response size exceeds safety limit")

                data = resp.read(max_bytes + 1)
                if len(data) > max_bytes:
                    raise RuntimeError("response exceeds safety limit")
                return FetchResult(data=data, final_url=final_url, content_type=content_type, status=status)
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in TRANSIENT_HTTP or attempt >= retries:
                raise RuntimeError(f"HTTP {exc.code} fetching {url}") from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            last_error = exc
            if attempt >= retries:
                raise RuntimeError(f"network failure fetching {url}: {exc}") from exc

        time.sleep(0.5 * (2**attempt))

    raise RuntimeError(f"fetch failed: {last_error}")

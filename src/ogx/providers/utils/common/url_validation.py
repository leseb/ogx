# Copyright (c) The OGX Contributors.
# All rights reserved.
#
# This source code is licensed under the terms described in the LICENSE file in
# the root directory of this source tree.

import ipaddress
import socket
from urllib.parse import urlparse

import httpx

_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _is_non_public_ip(addr: _IPAddress) -> bool:
    """Return True when an address is not publicly routable."""
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return _is_non_public_ip(addr.ipv4_mapped)
    return not addr.is_global


def _raise_blocked_ip_error(hostname: str) -> None:
    raise ValueError(f"Failed to fetch URL: requests to private IP addresses are not allowed ({hostname})")


def validate_url_not_private(url: str) -> None:
    """Reject URLs that resolve to private or loopback IP addresses.

    Raises:
        ValueError: If the URL hostname resolves to a blocked IP range or cannot be resolved.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Failed to parse hostname from URL: {url}")

    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError(f"Failed to resolve hostname: {hostname}") from exc
        for info in infos:
            addr = ipaddress.ip_address(info[4][0])
            if _is_non_public_ip(addr):
                _raise_blocked_ip_error(hostname)
        return

    if _is_non_public_ip(addr):
        _raise_blocked_ip_error(hostname)


class _SSRFSafeTransport(httpx.AsyncBaseTransport):
    """httpx transport wrapper that validates the peer address before every request."""

    def __init__(self, **kwargs: object) -> None:
        self._inner = httpx.AsyncHTTPTransport(**kwargs)  # type: ignore[arg-type]

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        hostname = request.url.host
        if hostname:
            validate_url_not_private(str(request.url))
        return await self._inner.handle_async_request(request)


async def fetch_with_ssrf_protection(
    url: str,
    *,
    timeout: httpx.Timeout | None = None,
) -> httpx.Response:
    """Fetch a URL with SSRF protection by validating DNS at request time.

    Resolves the hostname, validates all addresses are public, then fetches
    using the original URL (preserving TLS/SNI). The DNS validation happens
    inside the transport layer immediately before the connection is made,
    minimizing the TOCTOU window.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Failed to parse hostname from URL: {url}")

    if timeout is None:
        timeout = httpx.Timeout(30.0, connect=10.0)

    transport = _SSRFSafeTransport(verify=parsed.scheme == "https")

    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
    ) as client:
        r = await client.get(url)
        r.raise_for_status()
        return r

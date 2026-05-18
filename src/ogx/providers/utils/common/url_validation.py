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


def _resolve_and_validate(hostname: str, port: int | None) -> list[tuple[str, int]]:
    """Resolve hostname and validate all addresses are public.

    Returns a list of (ip, port) tuples that passed validation.
    """
    try:
        addr = ipaddress.ip_address(hostname)
        if _is_non_public_ip(addr):
            _raise_blocked_ip_error(hostname)
        return [(str(addr), port or 443)]
    except ValueError:
        pass

    try:
        infos = socket.getaddrinfo(hostname, port, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Failed to resolve hostname: {hostname}") from exc

    validated: list[tuple[str, int]] = []
    for info in infos:
        addr = ipaddress.ip_address(info[4][0])
        if _is_non_public_ip(addr):
            _raise_blocked_ip_error(hostname)
        validated.append((str(addr), int(info[4][1])))

    if not validated:
        raise ValueError(f"Failed to resolve hostname: {hostname}")

    return validated


async def fetch_with_ssrf_protection(
    url: str,
    *,
    timeout: httpx.Timeout | None = None,
) -> httpx.Response:
    """Fetch a URL with SSRF protection by pinning DNS resolution.

    Resolves the hostname, validates all addresses are public, then connects
    directly to the validated IP while preserving the original Host header.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname
    if not hostname:
        raise ValueError(f"Failed to parse hostname from URL: {url}")

    default_port = 443 if parsed.scheme == "https" else 80
    port = parsed.port or default_port

    validated_addrs = _resolve_and_validate(hostname, port)

    pinned_ip, pinned_port = validated_addrs[0]
    transport = httpx.AsyncHTTPTransport(
        verify=parsed.scheme == "https",
    )

    if timeout is None:
        timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
    ) as client:
        pinned_url = url.replace(f"://{hostname}", f"://{pinned_ip}", 1)
        if parsed.port:
            pinned_url = pinned_url.replace(f":{parsed.port}", f":{pinned_port}", 1)
        r = await client.get(
            pinned_url,
            headers={"Host": hostname},
        )
        r.raise_for_status()
        return r

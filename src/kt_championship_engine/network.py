from __future__ import annotations

import logging
import socket

import httpx2

logger = logging.getLogger(__name__)

_LIMITS = httpx2.Limits(max_connections=200, max_keepalive_connections=40, keepalive_expiry=30.0)
_SOCKET_OPTIONS = [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]


def _log_response(response: httpx2.Response) -> None:
    logger.info(
        "HTTP response received",
        extra={
            "http_method": response.request.method,
            "http_host": response.request.url.host,
            "http_status": response.status_code,
        },
    )


def create_client(*, timeout_seconds: float = 30.0, headers: dict[str, str] | None = None) -> httpx2.Client:
    """Create the shared HTTP/2 client with bounded timeouts and safe response logging."""

    transport = httpx2.HTTPTransport(
        http2=True,
        retries=3,
        limits=_LIMITS,
        socket_options=_SOCKET_OPTIONS,
    )
    return httpx2.Client(
        transport=transport,
        timeout=httpx2.Timeout(connect=5.0, read=timeout_seconds, write=10.0, pool=10.0),
        headers=headers or {},
        follow_redirects=True,
        event_hooks={"response": [_log_response]},
    )

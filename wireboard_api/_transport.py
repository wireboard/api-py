"""HTTP transport layer.

Two parallel implementations — sync (``Transport``) and async
(``AsyncTransport``) — sharing the response-parsing logic in
:func:`_parse_response_or_raise`.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, cast

import httpx

from ._serialize import serialize_params
from ._version import VERSION
from .errors import WireBoardApiError, WireBoardAuthError
from .types import RateLimitInfo

#: A callback that receives the rate-limit info parsed from each successful
#: response. Used by :meth:`WireBoardClient.with_meta`.
ResponseHook = Callable[[RateLimitInfo], None]

_USER_AGENT = f"wireboard-api-python/{VERSION}"


class TransportOptions:
    """Resolved transport configuration. Internal — built by the client."""

    __slots__ = ("token", "base_url", "retry_on_429", "timeout", "client", "_owns_client")

    def __init__(
        self,
        *,
        token: str,
        base_url: str,
        retry_on_429: bool,
        timeout: float | None,
        client: httpx.Client | httpx.AsyncClient | None,
    ) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.retry_on_429 = retry_on_429
        self.timeout = timeout
        self.client = client
        self._owns_client = client is None


# ─── Shared response parsing ────────────────────────────────────────────────


def _parse_rate_limit(headers: httpx.Headers) -> RateLimitInfo:
    return RateLimitInfo(
        limit=_num_or_none(headers.get("X-RateLimit-Limit")),
        remaining=_num_or_none(headers.get("X-RateLimit-Remaining")),
        retry_after=_num_or_none(headers.get("Retry-After")),
    )


def _num_or_none(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return None


def _parse_response_or_raise(response: httpx.Response) -> Any:
    """Inspect a finished response and either return the envelope's ``data``
    payload, or raise the appropriate WireBoard error.

    Caller handles the 429 retry separately (since that requires sleeping +
    re-issuing).
    """
    rate_limit = _parse_rate_limit(response.headers)
    status = response.status_code

    if status in (401, 403):
        body = _safe_json(response)
        message = f"HTTP {status}"
        if isinstance(body, dict):
            raw = body.get("message")
            if isinstance(raw, str):
                message = raw
        raise WireBoardAuthError(message, cast("Any", status))

    body = _safe_json(response)
    if body is None:
        raise WireBoardApiError(
            message=f"HTTP {status}: invalid JSON response",
            code=None,
            field_errors=None,
            http_status=status,
            rate_limit=rate_limit,
        )

    if isinstance(body, dict) and body.get("status") is True:
        return body.get("data"), rate_limit

    field_errors: dict[str, list[str]] | None = None
    code: str | None = None
    message = f"HTTP {status}"
    if isinstance(body, dict):
        raw_fe = body.get("fieldErrors")
        if isinstance(raw_fe, dict):
            field_errors = {
                str(k): [str(item) for item in v]
                for k, v in raw_fe.items()
                if isinstance(v, list)
            }
            ec = field_errors.get("error_code")
            if ec:
                code = ec[0]
        errors = body.get("errors")
        if isinstance(errors, list) and errors:
            first = errors[0]
            if isinstance(first, dict) and isinstance(first.get("text"), str):
                message = first["text"]
        elif isinstance(body.get("message"), str):
            message = body["message"]

    raise WireBoardApiError(
        message=message,
        code=code,
        field_errors=field_errors,
        http_status=status,
        rate_limit=rate_limit,
    )


def _build_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "User-Agent": _USER_AGENT,
        "X-WireBoard-Client": _USER_AGENT,
    }


def _build_params(
    params: dict[str, Any] | None,
) -> list[tuple[str, str | int | float | bool | None]] | None:
    if not params:
        return None
    # The serializer returns ``list[tuple[str, str]]`` which is assignment-
    # compatible with httpx's wider element type, but ``list`` is invariant
    # — widen here so the signature matches without needing a cast per call.
    return list(serialize_params(params))


# ─── Sync transport ─────────────────────────────────────────────────────────


class Transport:
    """Sync HTTP transport built on :class:`httpx.Client`.

    The transport is reused across calls. Owning code is responsible for
    closing it via :meth:`close`; the client classes do this automatically
    when used as a context manager.
    """

    def __init__(self, opts: TransportOptions) -> None:
        self._opts = opts
        client = opts.client if isinstance(opts.client, httpx.Client) else None
        if client is None:
            client = httpx.Client(timeout=opts.timeout)
            opts.client = client
            opts._owns_client = True
        self._client: httpx.Client = client
        self._response_hook: ResponseHook | None = None

    @property
    def client(self) -> httpx.Client:
        return self._client

    def set_response_hook(self, hook: ResponseHook | None) -> None:
        self._response_hook = hook

    def close(self) -> None:
        if self._opts._owns_client:
            self._client.close()

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return self._request("GET", path, params, did_retry=False)

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        did_retry: bool,
    ) -> Any:
        url = self._opts.base_url + path
        response = self._client.request(
            method,
            url,
            params=_build_params(params),
            headers=_build_headers(self._opts.token),
        )

        if (
            response.status_code == 429
            and self._opts.retry_on_429
            and not did_retry
        ):
            rate_limit = _parse_rate_limit(response.headers)
            ra = rate_limit["retry_after"]
            wait = 5 if ra is None else ra
            response.close()
            time.sleep(wait)
            return self._request(method, path, params, did_retry=True)

        try:
            data, rate_limit = _parse_response_or_raise(response)
        finally:
            response.close()
        if self._response_hook is not None:
            self._response_hook(rate_limit)
        return data


# ─── Async transport ────────────────────────────────────────────────────────


class AsyncTransport:
    """Async HTTP transport built on :class:`httpx.AsyncClient`."""

    def __init__(self, opts: TransportOptions) -> None:
        self._opts = opts
        client = opts.client if isinstance(opts.client, httpx.AsyncClient) else None
        if client is None:
            client = httpx.AsyncClient(timeout=opts.timeout)
            opts.client = client
            opts._owns_client = True
        self._client: httpx.AsyncClient = client
        self._response_hook: ResponseHook | None = None

    @property
    def client(self) -> httpx.AsyncClient:
        return self._client

    def set_response_hook(self, hook: ResponseHook | None) -> None:
        self._response_hook = hook

    async def aclose(self) -> None:
        if self._opts._owns_client:
            await self._client.aclose()

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        return await self._request("GET", path, params, did_retry=False)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None,
        did_retry: bool,
    ) -> Any:
        url = self._opts.base_url + path
        response = await self._client.request(
            method,
            url,
            params=_build_params(params),
            headers=_build_headers(self._opts.token),
        )

        if (
            response.status_code == 429
            and self._opts.retry_on_429
            and not did_retry
        ):
            rate_limit = _parse_rate_limit(response.headers)
            ra = rate_limit["retry_after"]
            wait = 5 if ra is None else ra
            await response.aclose()
            await asyncio.sleep(wait)
            return await self._request(method, path, params, did_retry=True)

        try:
            data, rate_limit = _parse_response_or_raise(response)
        finally:
            await response.aclose()
        if self._response_hook is not None:
            self._response_hook(rate_limit)
        return data

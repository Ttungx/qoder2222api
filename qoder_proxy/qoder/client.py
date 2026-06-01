import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import httpx

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.encoding import encode
from qoder_proxy.qoder.session import SessionBuilder, SessionContext
from qoder_proxy.qoder.signature import compose_bearer, sign_qoder_request


class QoderClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        client_version: str = "0.1.43",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.client_version = client_version
        self.transport = transport

    async def post_json(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any] | None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        encoded_body, headers = self._headers(session, path, body, accept="application/json")
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as client:
            response = await client.post(
                f"{self.api_base_url}{path}",
                content=encoded_body,
                headers=headers,
            )
        self._raise_for_status(response)
        return response.json()

    async def stream_sse(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        encoded_body, headers = self._headers(session, path, body, accept="text/event-stream")
        headers["cache-control"] = "no-cache"
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(transport=self.transport, timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.api_base_url}{path}",
                content=encoded_body,
                headers=headers,
            ) as response:
                self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if line:
                        yield line

    def _headers(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any] | None,
        *,
        accept: str,
    ) -> tuple[str, dict[str, str]]:
        encoded_body = ""
        if body is not None:
            encoded_body = encode(json.dumps(body, separators=(",", ":")).encode())
        payload_b64 = SessionBuilder.build_payload_b64(session.info)
        cosy_date = str(int(time.time()))
        signature = sign_qoder_request(
            payload_b64,
            session.cosy_key,
            cosy_date,
            encoded_body,
            _path_without_algo(path),
        )
        return encoded_body, {
            "cosy-data-policy": "AGREE",
            "content-type": "application/json",
            "cosy-machinetype": session.machine.machine_type,
            "cosy-clienttype": "5",
            "cosy-date": cosy_date,
            "cosy-user": session.identity.uid,
            "cosy-key": session.cosy_key,
            "accept": accept,
            "cosy-clientip": "169.254.198.161",
            "authorization": compose_bearer(payload_b64, signature),
            "accept-encoding": "identity",
            "cosy-version": self.client_version,
            "cosy-machineid": session.machine.machine_id,
            "cosy-machinetoken": session.machine.machine_token,
            "login-version": "v2",
            "user-agent": "Go-http-client/2.0",
        }

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code in {401, 403}:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                "Qoder upstream authentication failed",
                http_status=401,
                account_impact="disable",
            )
        if response.status_code == 429:
            raise CanonicalError(
                ErrorCode.RATE_LIMITED,
                "Qoder upstream rate limited",
                http_status=429,
            )
        raise CanonicalError(
            ErrorCode.UPSTREAM_ERROR,
            f"Qoder upstream returned HTTP {response.status_code}",
            http_status=502,
            retryable=response.status_code >= 500,
        )


def _path_without_algo(path: str) -> str:
    parsed = urlsplit(path)
    raw_path = parsed.path
    return raw_path.removeprefix("/algo")

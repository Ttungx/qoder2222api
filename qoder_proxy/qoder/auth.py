import json
from email.utils import formatdate
from typing import Any

import httpx

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.encoding import encode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity
from qoder_proxy.qoder.signature import APPCODE, sign_center_request


class QoderAuthClient:
    def __init__(
        self,
        *,
        center_base_url: str,
        client_version: str = "0.1.43",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.center_base_url = center_base_url.rstrip("/")
        self.client_version = client_version
        self.transport = transport

    async def exchange_pat(self, personal_token: str, machine: MachineIdentity) -> AuthIdentity:
        inner = {
            "personalToken": personal_token,
            "securityOauthToken": "",
            "refreshToken": "",
            "needRefresh": False,
            "authInfo": {},
        }
        outer = {
            "payload": json.dumps(inner, separators=(",", ":")),
            "encodeVersion": "1",
        }
        data = await self._post_encoded("/algo/api/v3/user/jobToken?Encode=1", outer, machine)
        return AuthIdentity(
            name=str(data.get("name", "")),
            aid=str(data.get("id", "")),
            uid=str(data.get("id", "")),
            user_type=str(data.get("userType", "personal_standard")),
            security_oauth_token=str(data.get("securityOauthToken", "")),
            refresh_token=str(data.get("refreshToken", "")),
        )

    async def user_status(self, user_id: str, machine: MachineIdentity) -> dict[str, Any]:
        inner = {
            "userId": user_id,
            "personalToken": "",
            "securityOauthToken": "",
            "refreshToken": "",
            "needRefresh": False,
            "authInfo": {},
        }
        outer = {
            "payload": json.dumps(inner, separators=(",", ":")),
            "encodeVersion": "1",
        }
        return await self._post_encoded("/algo/api/v3/user/status?Encode=1", outer, machine)

    async def _post_encoded(
        self,
        path: str,
        payload: dict[str, Any],
        machine: MachineIdentity,
    ) -> dict[str, Any]:
        date = formatdate(usegmt=True)
        body = encode(json.dumps(payload, separators=(",", ":")).encode())
        headers = {
            "cosy-machinetoken": machine.machine_token,
            "cosy-machinetype": machine.machine_type,
            "login-version": "v2",
            "appcode": APPCODE,
            "accept": "application/json",
            "accept-encoding": "identity",
            "cosy-version": self.client_version,
            "cosy-clienttype": "5",
            "date": date,
            "signature": sign_center_request(date),
            "content-type": "application/json",
            "cosy-machineid": machine.machine_id,
            "user-agent": "Go-http-client/2.0",
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            response = await client.post(
                f"{self.center_base_url}{path}",
                content=body,
                headers=headers,
            )
        if response.status_code in {401, 403}:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                "Qoder authentication failed",
                http_status=401,
                account_impact="disable",
            )
        if response.status_code != 200:
            raise CanonicalError(
                ErrorCode.UPSTREAM_ERROR,
                f"Qoder center API returned HTTP {response.status_code}",
                http_status=502,
                retryable=response.status_code >= 500,
            )
        return response.json()

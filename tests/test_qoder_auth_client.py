import asyncio
import json

import httpx
import pytest

from qoder_proxy.canonical.errors import ErrorCode
from qoder_proxy.qoder.auth import QoderAuthClient
from qoder_proxy.qoder.encoding import decode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity


def test_exchange_pat_posts_encoded_payload_and_returns_identity() -> None:
    async def run() -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(decode(request.content.decode()).decode())
            return httpx.Response(
                200,
                json={
                    "name": "User",
                    "id": "user-1",
                    "userType": "personal_standard",
                    "securityOauthToken": "oauth-token",
                    "refreshToken": "refresh-token",
                },
            )

        client = QoderAuthClient(
            center_base_url="https://center.example.test",
            transport=httpx.MockTransport(handler),
        )
        machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")

        identity = await client.exchange_pat("pat-secret", machine)

        assert isinstance(identity, AuthIdentity)
        assert identity.uid == "user-1"
        assert identity.security_oauth_token == "oauth-token"
        assert captured["url"] == "https://center.example.test/algo/api/v3/user/jobToken?Encode=1"
        assert captured["body"] == {
            "payload": json.dumps(
                {
                    "personalToken": "pat-secret",
                    "securityOauthToken": "",
                    "refreshToken": "",
                    "needRefresh": False,
                    "authInfo": {},
                },
                separators=(",", ":"),
            ),
            "encodeVersion": "1",
        }
        headers = captured["headers"]
        assert headers["cosy-machineid"] == "mid"
        assert headers["cosy-machinetoken"] == "mtok"
        assert headers["cosy-machinetype"] == "mtype"
        assert headers["appcode"] == "cosy"
        assert "signature" in headers

    asyncio.run(run())


def test_exchange_pat_raises_authentication_failed_on_401() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="bad token")

        client = QoderAuthClient(
            center_base_url="https://center.example.test",
            transport=httpx.MockTransport(handler),
        )

        with pytest.raises(Exception) as error:
            await client.exchange_pat(
                "bad",
                MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype"),
            )

        assert error.value.code is ErrorCode.AUTHENTICATION_FAILED

    asyncio.run(run())

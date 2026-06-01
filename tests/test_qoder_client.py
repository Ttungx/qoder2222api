import asyncio
import json

import httpx

from qoder_proxy.qoder.client import QoderClient
from qoder_proxy.qoder.encoding import decode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


def _session():
    return SessionBuilder.new_session(
        AuthIdentity(name="User", aid="aid", uid="uid", user_type="personal_standard"),
        MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype"),
        temp_key=b"1234567890abcdef",
    )


def test_post_json_sends_encoded_body_and_signed_headers() -> None:
    async def run() -> None:
        captured: dict[str, object] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            captured["url"] = str(request.url)
            captured["headers"] = dict(request.headers)
            captured["body"] = json.loads(decode(request.content.decode()).decode())
            return httpx.Response(200, json={"ok": True})

        client = QoderClient(
            api_base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
        )

        response = await client.post_json(_session(), "/algo/api/test?Encode=1", {"hello": "world"})

        assert response == {"ok": True}
        assert captured["url"] == "https://api.example.test/algo/api/test?Encode=1"
        assert captured["body"] == {"hello": "world"}
        headers = captured["headers"]
        assert headers["authorization"].startswith("Bearer COSY.")
        assert headers["cosy-machineid"] == "mid"
        assert headers["cosy-machinetoken"] == "mtok"
        assert headers["cosy-key"]
        assert headers["accept"] == "application/json"

    asyncio.run(run())


def test_stream_sse_yields_non_empty_sse_lines() -> None:
    async def run() -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                content=(
                    b'data: {"body":"{\\"choices\\":[{\\"delta\\":{'
                    b'\\"content\\":\\"hi\\"}}]}"}\n\n'
                ),
                headers={"content-type": "text/event-stream"},
            )

        client = QoderClient(
            api_base_url="https://api.example.test",
            transport=httpx.MockTransport(handler),
        )

        lines = [
            line
            async for line in client.stream_sse(_session(), "/algo/api/test?Encode=1", {"x": 1})
        ]

        assert lines == [
            'data: {"body":"{\\"choices\\":[{\\"delta\\":{\\"content\\":\\"hi\\"}}]}"}'
        ]

    asyncio.run(run())

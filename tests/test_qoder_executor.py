import asyncio
import json

from qoder_proxy.accounts.models import Account
from qoder_proxy.canonical.types import (
    CanonicalContentBlock,
    CanonicalMessage,
    CanonicalRequest,
    ClientProtocol,
    MessageRole,
    ModelInfo,
)
from qoder_proxy.qoder.executor import QoderExecutor
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


class FakeQoderClient:
    def __init__(self) -> None:
        self.extra_headers = None
        self.body = None

    async def stream_sse(self, session, path, body, extra_headers=None):
        self.body = body
        self.extra_headers = extra_headers
        inner = {"choices": [{"delta": {"content": "hello"}}]}
        yield "data: " + json.dumps({"body": json.dumps(inner)})


def _account() -> Account:
    identity = AuthIdentity(name="User", aid="aid", uid="uid", user_type="personal_standard")
    machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")
    session = SessionBuilder.new_session(identity, machine, temp_key=b"1234567890abcdef")
    return Account(
        id="acct_1",
        display_name="main",
        source="pat",
        identity=identity,
        machine=machine,
        session_info=session.info,
        session_cosy_key=session.cosy_key,
    )


def _request() -> CanonicalRequest:
    return CanonicalRequest(
        model="claude-sonnet-4-5",
        resolved_model=ModelInfo(
            alias="claude-sonnet-4-5",
            qoder_key="lite",
            qoder_source="system",
        ),
        messages=[
            CanonicalMessage(
                role=MessageRole.USER,
                content=[CanonicalContentBlock.text_block("hi")],
            )
        ],
        stream=True,
        client_protocol=ClientProtocol.ANTHROPIC,
    )


def test_qoder_executor_streams_canonical_text_events() -> None:
    async def run() -> None:
        client = FakeQoderClient()
        executor = QoderExecutor(client)

        events = [event async for event in executor.execute(_request(), _account())]

        assert events[0].type == "response_start"
        assert events[1].type == "text_delta"
        assert events[1].text == "hello"
        assert events[-1].type == "response_stop"
        assert client.extra_headers == {"x-model-key": "lite", "x-model-source": "system"}
        assert client.body["chat_context"]["text"]["text"] == "hi"

    asyncio.run(run())

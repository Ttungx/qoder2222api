from collections.abc import AsyncIterator

from qoder_proxy.accounts.models import Account
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import CanonicalEvent, CanonicalRequest
from qoder_proxy.qoder.payload import build_qoder_payload
from qoder_proxy.qoder.session import SessionContext
from qoder_proxy.qoder.sse import parse_qoder_sse_data

GENERATION_PATH = (
    "/algo/api/v2/service/pro/sse/agent_chat_generation"
    "?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"
)


class QoderExecutor:
    def __init__(self, client) -> None:
        self.client = client

    async def execute(
        self,
        request: CanonicalRequest,
        account: Account,
    ) -> AsyncIterator[CanonicalEvent]:
        if account.identity is None or account.machine is None:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                f"Account {account.id} has no Qoder session identity",
                http_status=401,
            )
        session = SessionContext(
            temp_key=b"",
            cosy_key=account.session_cosy_key or "",
            info=account.session_info or "",
            identity=account.identity,
            machine=account.machine,
        )
        if not session.cosy_key or not session.info:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                f"Account {account.id} has no active Qoder session",
                http_status=401,
            )
        model = request.resolved_model
        extra_headers = {
            "x-model-key": model.qoder_key if model else request.model,
            "x-model-source": model.qoder_source if model else "system",
        }
        payload = build_qoder_payload(request, user_type=account.identity.user_type)
        yield CanonicalEvent(type="response_start")
        async for line in self.client.stream_sse(
            session,
            GENERATION_PATH,
            payload,
            extra_headers=extra_headers,
        ):
            if not line.startswith("data:"):
                continue
            raw_data = line.removeprefix("data:").strip()
            for event in parse_qoder_sse_data(raw_data):
                yield event
        yield CanonicalEvent(type="response_stop", finish_reason="end_turn")

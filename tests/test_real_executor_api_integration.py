from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from qoder_proxy.api.app import create_app
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import CanonicalEvent
from qoder_proxy.config.models import ExecutorConfig, ProxyConfig


class FakeAccountPool:
    def __init__(self) -> None:
        self.selected_model = None
        self.success_account_id = None
        self.error_account_id = None
        self.error = None

    async def select_for_model(self, qoder_key: str):
        self.selected_model = qoder_key
        return type("Account", (), {"id": "acct_1"})()

    def apply_success(self, account_id: str) -> None:
        self.success_account_id = account_id

    def apply_error(self, account_id: str, error) -> None:
        self.error_account_id = account_id
        self.error = error


class FakeExecutor:
    async def execute(self, request, account) -> AsyncIterator[CanonicalEvent]:
        yield CanonicalEvent(type="response_start")
        yield CanonicalEvent(type="text_delta", text=f"real {request.model}")
        yield CanonicalEvent(type="response_stop", finish_reason="end_turn")


class FailingStreamExecutor:
    async def execute(self, request, account) -> AsyncIterator[CanonicalEvent]:
        yield CanonicalEvent(type="response_start")
        raise CanonicalError(ErrorCode.RATE_LIMITED, "slow", http_status=429)


def test_messages_route_uses_real_executor_when_configured() -> None:
    pool = FakeAccountPool()
    app = create_app(
        ProxyConfig(executor=ExecutorConfig(mode="qoder")),
        account_pool=pool,
        qoder_executor=FakeExecutor(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "real claude-sonnet-4-5"
    assert pool.selected_model == "lite"
    assert pool.success_account_id == "acct_1"


def test_streaming_route_updates_account_error_when_real_executor_fails() -> None:
    pool = FakeAccountPool()
    app = create_app(
        ProxyConfig(executor=ExecutorConfig(mode="qoder")),
        account_pool=pool,
        qoder_executor=FailingStreamExecutor(),
    )
    client = TestClient(app)

    with client.stream(
        "POST",
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 10,
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
    ) as response:
        body = response.read().decode()

    assert response.status_code == 200
    assert "event: error" in body
    assert pool.error_account_id == "acct_1"
    assert pool.error.code is ErrorCode.RATE_LIMITED

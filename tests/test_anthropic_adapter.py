import pytest
from fastapi.testclient import TestClient

from qoder_proxy.adapters.anthropic import AnthropicMessageRequest, request_to_canonical
from qoder_proxy.api.app import create_app
from qoder_proxy.canonical.types import ContentBlockType, MessageRole


def test_anthropic_request_to_canonical_text() -> None:
    request = AnthropicMessageRequest.model_validate(
        {
            "model": "claude-sonnet-4-5",
            "max_tokens": 100,
            "system": [{"type": "text", "text": "be brief"}],
            "messages": [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
        }
    )

    canonical = request_to_canonical(request)

    assert canonical.system == "be brief"
    assert canonical.messages[0].role is MessageRole.USER
    assert canonical.messages[0].content[0].type is ContentBlockType.TEXT
    assert canonical.messages[0].content[0].text == "hello"


def test_messages_non_stream_mock_response() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 100,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "message"
    assert body["role"] == "assistant"
    assert body["content"][0]["type"] == "text"
    assert "Mock Qoder response" in body["content"][0]["text"]


def test_models_endpoint() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/models")

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "list"
    assert {model["id"] for model in body["data"]} >= {"claude-sonnet-4-5", "gpt-5-codex"}


@pytest.mark.parametrize("stream", [True])
def test_messages_stream_mock_response(stream: bool) -> None:
    client = TestClient(create_app())

    with client.stream(
        "POST",
        "/v1/messages",
        json={
            "model": "claude-sonnet-4-5",
            "max_tokens": 100,
            "stream": stream,
            "messages": [{"role": "user", "content": "hello"}],
        },
    ) as response:
        text = response.read().decode()

    assert response.status_code == 200
    assert "event: message_start" in text
    assert "event: content_block_delta" in text
    assert "event: message_stop" in text

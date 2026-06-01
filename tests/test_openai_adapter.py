from fastapi.testclient import TestClient

from qoder_proxy.adapters.openai import OpenAIChatRequest, request_to_canonical
from qoder_proxy.api.app import create_app
from qoder_proxy.canonical.types import ContentBlockType, MessageRole


def test_openai_request_to_canonical_text_and_tool_result() -> None:
    request = OpenAIChatRequest.model_validate(
        {
            "model": "gpt-5-codex",
            "messages": [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hello"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "read", "arguments": "{\"path\":\"a\"}"},
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_1", "content": "file text"},
            ],
            "max_tokens": 100,
        }
    )

    canonical = request_to_canonical(request)

    assert canonical.system == "be brief"
    assert canonical.messages[0].role is MessageRole.USER
    assert canonical.messages[0].content[0].text == "hello"
    assert canonical.messages[1].content[0].type is ContentBlockType.TOOL_CALL
    assert canonical.messages[1].content[0].tool_call.name == "read"
    assert canonical.messages[2].content[0].type is ContentBlockType.TOOL_RESULT
    assert canonical.messages[2].content[0].tool_result.tool_call_id == "call_1"


def test_chat_completions_non_stream_mock_response() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/chat/completions",
        json={
            "model": "gpt-5-codex",
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["object"] == "chat.completion"
    assert body["model"] == "gpt-5-codex"
    assert body["choices"][0]["message"]["role"] == "assistant"
    assert "Mock Qoder response" in body["choices"][0]["message"]["content"]
    assert body["usage"]["total_tokens"] >= 0


def test_chat_completions_stream_mock_response() -> None:
    client = TestClient(create_app())

    with client.stream(
        "POST",
        "/v1/chat/completions",
        json={
            "model": "gpt-5-codex",
            "stream": True,
            "messages": [{"role": "user", "content": "hello"}],
        },
    ) as response:
        text = response.read().decode()

    assert response.status_code == 200
    assert "chat.completion.chunk" in text
    assert "data: [DONE]" in text


def test_chat_completions_unknown_model_uses_openai_error_shape() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/chat/completions",
        json={"model": "missing", "messages": [{"role": "user", "content": "hello"}]},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["error"]["type"] == "unknown_model"

from fastapi.testclient import TestClient

from qoder_proxy.api.app import create_app
from qoder_proxy.config.models import ProxyConfig, ServerConfig


def test_api_key_middleware_rejects_missing_key() -> None:
    app = create_app(ProxyConfig(server=ServerConfig(api_keys=["secret"])))
    client = TestClient(app)

    response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["type"] == "authentication_failed"


def test_api_key_middleware_accepts_bearer_key() -> None:
    app = create_app(ProxyConfig(server=ServerConfig(api_keys=["secret"])))
    client = TestClient(app)

    response = client.get("/v1/models", headers={"authorization": "Bearer secret"})

    assert response.status_code == 200


def test_unknown_model_error_shapes_for_both_protocols() -> None:
    client = TestClient(create_app())

    anthropic = client.post(
        "/v1/messages",
        json={
            "model": "missing",
            "max_tokens": 10,
            "messages": [{"role": "user", "content": "hi"}],
        },
    )
    openai = client.post(
        "/v1/chat/completions",
        json={"model": "missing", "messages": [{"role": "user", "content": "hi"}]},
    )

    assert anthropic.status_code == 404
    assert anthropic.json()["detail"]["error"]["type"] == "unknown_model"
    assert openai.status_code == 404
    assert openai.json()["detail"]["error"]["type"] == "unknown_model"

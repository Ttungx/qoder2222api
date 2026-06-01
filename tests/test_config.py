from pathlib import Path

import pytest

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.config import ModelResolver, default_config_yaml, load_config


def test_default_config_yaml_contains_models() -> None:
    content = default_config_yaml()

    assert "claude-sonnet-4-5" in content
    assert "gpt-5-codex" in content


def test_load_config_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
server:
  host: 0.0.0.0
  port: 9000
models:
  - alias: claude-test
    qoder_key: pro
    qoder_source: system
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.server.host == "0.0.0.0"
    assert config.server.port == 9000
    assert config.models[0].alias == "claude-test"


def test_model_resolver_unknown_model() -> None:
    resolver = ModelResolver(load_config(Path("missing-config.yaml")).models)

    with pytest.raises(CanonicalError) as error:
        resolver.resolve("missing")

    assert error.value.code is ErrorCode.UNKNOWN_MODEL
    assert error.value.http_status == 404

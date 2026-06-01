import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import ModelInfo


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8963, ge=1, le=65535)
    api_keys: list[str] = Field(default_factory=list)
    trusted_proxies: list[str] = Field(default_factory=list)


class StorageConfig(BaseModel):
    path: str = "./data/qoder-proxy.db"


class LoggingConfig(BaseModel):
    level: str = "info"


class ModelAliasConfig(BaseModel):
    alias: str
    qoder_key: str
    qoder_source: str = "system"


class AccountConfig(BaseModel):
    name: str | None = None
    pat: str | None = None
    pat_env: str | None = None
    enabled: bool = True


class ExecutorConfig(BaseModel):
    mode: str = Field(default="mock", pattern="^(mock|qoder)$")


class AccountsConfig(BaseModel):
    storage_path: str = "./data/accounts.json"


class QoderConfig(BaseModel):
    center_base_url: str = "https://center.qoder.sh"
    api_base_url: str = "https://api3.qoder.sh"
    client_version: str = "0.1.43"


class ProxyConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
    account_seeds: list[AccountConfig] = Field(default_factory=list)
    qoder: QoderConfig = Field(default_factory=QoderConfig)
    models: list[ModelAliasConfig] = Field(default_factory=list)

    def resolved_models(self) -> list[ModelInfo]:
        return [ModelInfo(**model.model_dump()) for model in self.models]


DEFAULT_CONFIG = ProxyConfig(
    models=[
        ModelAliasConfig(alias="claude-sonnet-4-5", qoder_key="lite", qoder_source="system"),
        ModelAliasConfig(alias="gpt-5-codex", qoder_key="lite", qoder_source="system"),
    ]
)


def default_config_yaml() -> str:
    data = DEFAULT_CONFIG.model_dump(mode="json")
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def load_config(path: str | Path | None = None) -> ProxyConfig:
    config_path = Path(path or os.getenv("QODER_PROXY_CONFIG", "config.yaml"))
    if config_path.exists():
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise CanonicalError(ErrorCode.INVALID_REQUEST, "config.yaml must contain a mapping")
        config = ProxyConfig.model_validate(raw)
    else:
        config = DEFAULT_CONFIG.model_copy(deep=True)

    if host := os.getenv("QODER_PROXY_HOST"):
        config.server.host = host
    if port := os.getenv("QODER_PROXY_PORT"):
        config.server.port = int(port)
    if storage_path := os.getenv("QODER_PROXY_STORAGE_PATH"):
        config.storage.path = storage_path
    if log_level := os.getenv("QODER_PROXY_LOG_LEVEL"):
        config.logging.level = log_level
    if executor_mode := os.getenv("QODER_PROXY_EXECUTOR"):
        config.executor.mode = executor_mode
    if accounts_path := os.getenv("QODER_PROXY_ACCOUNTS_PATH"):
        config.accounts.storage_path = accounts_path
    if center_base_url := os.getenv("QODER_CENTER_BASE_URL"):
        config.qoder.center_base_url = center_base_url
    if api_base_url := os.getenv("QODER_API_BASE_URL"):
        config.qoder.api_base_url = api_base_url
    return config


class ModelResolver:
    def __init__(self, models: list[ModelAliasConfig]) -> None:
        self._models = {model.alias: ModelInfo(**model.model_dump()) for model in models}

    def list_models(self) -> list[ModelInfo]:
        return list(self._models.values())

    def resolve(self, alias: str) -> ModelInfo:
        try:
            return self._models[alias]
        except KeyError as exc:
            raise CanonicalError(
                ErrorCode.UNKNOWN_MODEL,
                f"Unknown model alias: {alias}",
                http_status=404,
            ) from exc


def model_to_openai(model: ModelInfo) -> dict[str, Any]:
    return {
        "id": model.alias,
        "object": "model",
        "created": 0,
        "owned_by": "qoder",
    }

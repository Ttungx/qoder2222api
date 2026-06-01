from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AccountHealth(StrEnum):
    OK = "ok"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UPSTREAM_ERROR = "upstream_error"


class QuotaSnapshot(BaseModel):
    remaining: int | None = None
    limit: int | None = None
    refreshed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Account(BaseModel):
    id: str
    display_name: str
    source: str
    enabled: bool = True
    pat: str | None = None
    pat_env: str | None = None
    supported_models: list[str] = Field(default_factory=list)
    quota: QuotaSnapshot | None = None
    health: AccountHealth = AccountHealth.OK
    failure_count: int = 0
    cooldown_until: datetime | None = None

    def supports_model(self, qoder_key: str) -> bool:
        return not self.supported_models or qoder_key in self.supported_models

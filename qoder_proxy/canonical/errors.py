from enum import StrEnum

from pydantic import BaseModel, Field


class ErrorCode(StrEnum):
    INVALID_REQUEST = "invalid_request"
    UNSUPPORTED_FEATURE = "unsupported_feature"
    UNKNOWN_MODEL = "unknown_model"
    NO_AVAILABLE_ACCOUNT = "no_available_account"
    AUTHENTICATION_FAILED = "authentication_failed"
    RATE_LIMITED = "rate_limited"
    QUOTA_EXHAUSTED = "quota_exhausted"
    UPSTREAM_ERROR = "upstream_error"
    STREAM_INTERRUPTED = "stream_interrupted"
    INTERNAL_ERROR = "internal_error"


class CanonicalError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        *,
        http_status: int = 400,
        retryable: bool = False,
        account_impact: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = retryable
        self.account_impact = account_impact

    def to_payload(self) -> dict[str, object]:
        return CanonicalErrorPayload(
            code=self.code,
            message=self.message,
            http_status=self.http_status,
            retryable=self.retryable,
            account_impact=self.account_impact,
        ).model_dump(exclude_none=True)


class CanonicalErrorPayload(BaseModel):
    code: ErrorCode
    message: str
    http_status: int = Field(ge=100, le=599)
    retryable: bool = False
    account_impact: str | None = None

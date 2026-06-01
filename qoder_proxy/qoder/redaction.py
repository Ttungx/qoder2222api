from typing import Any

SENSITIVE_KEYS = {
    "authorization",
    "bearer",
    "cosy-key",
    "cosy-machinetoken",
    "cosy-machineid",
    "machinetoken",
    "machineid",
    "machineToken",
    "machineId",
    "personalToken",
    "pat",
    "refreshToken",
    "securityOauthToken",
    "signature",
}


def redact_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _mask(item) if _is_sensitive_key(key) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_sensitive(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("_", "").replace("-", "").lower()
    return any(
        normalized == sensitive.replace("_", "").replace("-", "").lower()
        for sensitive in SENSITIVE_KEYS
    )


def _mask(value: Any) -> str:
    text = str(value)
    if len(text) <= 8:
        return "****"
    if text.startswith("Bearer "):
        return f"{text[:4]}...{text[-3:]}"
    return f"{text[:4]}...{text[-4:]}"

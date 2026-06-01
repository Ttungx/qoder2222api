import json
from typing import Any

from qoder_proxy.canonical.types import CanonicalEvent, CanonicalToolCall


def parse_qoder_sse_data(data: str) -> list[CanonicalEvent]:
    try:
        wrapper = json.loads(data)
        body = wrapper.get("body") or ""
        if not body:
            return []
        inner = json.loads(body)
    except json.JSONDecodeError:
        return []

    events: list[CanonicalEvent] = []
    for choice in inner.get("choices") or []:
        delta = choice.get("delta") or {}
        content = delta.get("content")
        if content:
            events.append(CanonicalEvent(type="text_delta", text=content))
        for tool_call in delta.get("tool_calls") or []:
            function = tool_call.get("function") or {}
            events.append(
                CanonicalEvent(
                    type="tool_call_delta",
                    tool_call=CanonicalToolCall(
                        id=str(tool_call.get("id", "")),
                        name=str(function.get("name", "")),
                        arguments=_arguments(function.get("arguments")),
                    ),
                )
            )
    return events


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {"raw": value}
    return parsed if isinstance(parsed, dict) else {"raw": value}

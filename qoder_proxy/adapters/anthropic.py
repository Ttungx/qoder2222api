import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import (
    CanonicalContentBlock,
    CanonicalEvent,
    CanonicalMessage,
    CanonicalRequest,
    CanonicalToolCall,
    CanonicalToolResult,
    ClientProtocol,
    GenerationOptions,
    MessageRole,
    ModelInfo,
)


class AnthropicMessageRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    system: str | list[dict[str, Any]] | None = None
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: dict[str, Any] | str | None = None
    max_tokens: int = Field(gt=0)
    stop_sequences: list[str] = Field(default_factory=list)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stream: bool = False


def request_to_canonical(
    request: AnthropicMessageRequest,
    resolved_model: ModelInfo | None = None,
) -> CanonicalRequest:
    return CanonicalRequest(
        model=request.model,
        resolved_model=resolved_model,
        system=_system_to_text(request.system),
        messages=[_message_to_canonical(message) for message in request.messages],
        tools=request.tools,
        tool_choice=request.tool_choice,
        options=GenerationOptions(
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stop_sequences=request.stop_sequences,
        ),
        stream=request.stream,
        client_protocol=ClientProtocol.ANTHROPIC,
    )


def _system_to_text(system: str | list[dict[str, Any]] | None) -> str | None:
    if system is None or isinstance(system, str):
        return system
    parts: list[str] = []
    for block in system:
        if block.get("type") != "text":
            raise CanonicalError(
                ErrorCode.UNSUPPORTED_FEATURE,
                "Only text system blocks are supported",
            )
        parts.append(str(block.get("text", "")))
    return "\n".join(parts)


def _message_to_canonical(message: dict[str, Any]) -> CanonicalMessage:
    role = MessageRole(message.get("role"))
    raw_content = message.get("content", [])
    if isinstance(raw_content, str):
        blocks = [CanonicalContentBlock.text_block(raw_content)]
    else:
        blocks = [_content_block_to_canonical(block) for block in raw_content]
    return CanonicalMessage(role=role, content=blocks)


def _content_block_to_canonical(block: dict[str, Any]) -> CanonicalContentBlock:
    block_type = block.get("type")
    if block_type == "text":
        return CanonicalContentBlock.text_block(str(block.get("text", "")))
    if block_type == "tool_use":
        return CanonicalContentBlock.tool_call_block(
            CanonicalToolCall(
                id=str(block.get("id", "")),
                name=str(block.get("name", "")),
                arguments=block.get("input") or {},
            )
        )
    if block_type == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            content = "".join(
                str(item.get("text", ""))
                for item in content
                if item.get("type") == "text"
            )
        return CanonicalContentBlock.tool_result_block(
            CanonicalToolResult(
                tool_call_id=str(block.get("tool_use_id", "")),
                content=str(content),
                is_error=bool(block.get("is_error", False)),
            )
        )
    raise CanonicalError(
        ErrorCode.UNSUPPORTED_FEATURE,
        f"Unsupported Anthropic content block: {block_type}",
    )


async def canonical_events_to_message(
    events: AsyncIterator[CanonicalEvent],
    *,
    model: str,
) -> dict[str, Any]:
    text_parts: list[str] = []
    stop_reason = "end_turn"
    usage = {"input_tokens": 0, "output_tokens": 0}
    async for event in events:
        if event.type == "text_delta" and event.text:
            text_parts.append(event.text)
        elif event.type == "response_metadata" and event.usage:
            usage.update(event.usage)
        elif event.type == "response_stop" and event.finish_reason:
            stop_reason = event.finish_reason
        elif event.type == "error" and event.error:
            raise CanonicalError(ErrorCode.UPSTREAM_ERROR, str(event.error), http_status=502)
    return {
        "id": f"msg_{uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": model,
        "content": [{"type": "text", "text": "".join(text_parts)}],
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": usage,
    }


async def canonical_events_to_sse(
    events: AsyncIterator[CanonicalEvent],
    *,
    model: str,
) -> AsyncIterator[str]:
    message_id = f"msg_{uuid4().hex}"
    yield _sse(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "type": "message",
                "role": "assistant",
                "model": model,
                "content": [],
                "stop_reason": None,
                "stop_sequence": None,
                "usage": {"input_tokens": 0, "output_tokens": 0},
            },
        },
    )
    yield _sse(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {"type": "text", "text": ""},
        },
    )
    async for event in events:
        if event.type == "text_delta" and event.text:
            yield _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": event.text},
                },
            )
        elif event.type == "response_metadata" and event.usage:
            yield _sse(
                "message_delta",
                {"type": "message_delta", "delta": {}, "usage": event.usage},
            )
        elif event.type == "response_stop":
            yield _sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield _sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {
                        "stop_reason": event.finish_reason or "end_turn",
                        "stop_sequence": None,
                    },
                },
            )
            yield _sse("message_stop", {"type": "message_stop"})
        elif event.type == "error" and event.error:
            yield _sse("error", {"type": "error", "error": event.error})


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

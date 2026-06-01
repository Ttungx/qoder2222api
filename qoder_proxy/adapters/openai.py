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


class OpenAIChatRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: dict[str, Any] | str | None = None
    stream: bool = False
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    max_tokens: int | None = Field(default=None, gt=0)
    stop: str | list[str] | None = None


def request_to_canonical(
    request: OpenAIChatRequest,
    resolved_model: ModelInfo | None = None,
) -> CanonicalRequest:
    system_parts: list[str] = []
    messages: list[CanonicalMessage] = []
    for message in request.messages:
        converted = _message_to_canonical(message)
        if converted.role is MessageRole.SYSTEM:
            system_parts.extend(block.text or "" for block in converted.content)
        else:
            messages.append(converted)
    return CanonicalRequest(
        model=request.model,
        resolved_model=resolved_model,
        system="\n".join(part for part in system_parts if part) or None,
        messages=messages,
        tools=request.tools,
        tool_choice=request.tool_choice,
        options=GenerationOptions(
            max_tokens=request.max_tokens,
            temperature=request.temperature,
            top_p=request.top_p,
            stop_sequences=_stop_sequences(request.stop),
        ),
        stream=request.stream,
        client_protocol=ClientProtocol.OPENAI,
    )


def _message_to_canonical(message: dict[str, Any]) -> CanonicalMessage:
    role = MessageRole(message.get("role"))
    if role is MessageRole.TOOL:
        return CanonicalMessage(
            role=role,
            content=[
                CanonicalContentBlock.tool_result_block(
                    CanonicalToolResult(
                        tool_call_id=str(message.get("tool_call_id", "")),
                        content=str(message.get("content") or ""),
                    )
                )
            ],
        )

    blocks: list[CanonicalContentBlock] = []
    content = message.get("content")
    if isinstance(content, str):
        blocks.append(CanonicalContentBlock.text_block(content))
    elif isinstance(content, list):
        blocks.extend(_content_part_to_canonical(part) for part in content)
    for tool_call in message.get("tool_calls") or []:
        blocks.append(_tool_call_to_canonical(tool_call))
    return CanonicalMessage(role=role, content=blocks)


def _content_part_to_canonical(part: dict[str, Any]) -> CanonicalContentBlock:
    if part.get("type") == "text":
        return CanonicalContentBlock.text_block(str(part.get("text", "")))
    raise CanonicalError(
        ErrorCode.UNSUPPORTED_FEATURE,
        f"Unsupported OpenAI content part: {part.get('type')}",
    )


def _tool_call_to_canonical(tool_call: dict[str, Any]) -> CanonicalContentBlock:
    function = tool_call.get("function") or {}
    raw_arguments = function.get("arguments") or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
    except json.JSONDecodeError:
        arguments = {"raw": raw_arguments}
    return CanonicalContentBlock.tool_call_block(
        CanonicalToolCall(
            id=str(tool_call.get("id", "")),
            name=str(function.get("name", "")),
            arguments=arguments,
        )
    )


def _stop_sequences(stop: str | list[str] | None) -> list[str]:
    if stop is None:
        return []
    if isinstance(stop, str):
        return [stop]
    return stop


async def canonical_events_to_chat_completion(
    events: AsyncIterator[CanonicalEvent],
    *,
    model: str,
) -> dict[str, Any]:
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    text_parts: list[str] = []
    finish_reason = "stop"
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    async for event in events:
        if event.type == "text_delta" and event.text:
            text_parts.append(event.text)
        elif event.type == "response_metadata" and event.usage:
            usage = _openai_usage(event.usage)
        elif event.type == "response_stop":
            finish_reason = _finish_reason(event.finish_reason)
        elif event.type == "error" and event.error:
            raise CanonicalError(ErrorCode.UPSTREAM_ERROR, str(event.error), http_status=502)
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "".join(text_parts)},
                "finish_reason": finish_reason,
            }
        ],
        "usage": usage,
    }


async def canonical_events_to_chat_sse(
    events: AsyncIterator[CanonicalEvent],
    *,
    model: str,
) -> AsyncIterator[str]:
    completion_id = f"chatcmpl-{uuid4().hex[:24]}"
    yield _sse(
        {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": 0,
            "model": model,
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        }
    )
    async for event in events:
        if event.type == "text_delta" and event.text:
            yield _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": event.text},
                            "finish_reason": None,
                        }
                    ],
                }
            )
        elif event.type == "response_stop":
            yield _sse(
                {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": _finish_reason(event.finish_reason),
                        }
                    ],
                }
            )
            yield "data: [DONE]\n\n"
        elif event.type == "error" and event.error:
            yield f"data: {json.dumps({'error': event.error}, ensure_ascii=False)}\n\n"


def _sse(data: dict[str, Any]) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _finish_reason(reason: str | None) -> str:
    if reason in {None, "end_turn", "stop"}:
        return "stop"
    if reason in {"tool_use", "tool_calls"}:
        return "tool_calls"
    return reason


def _openai_usage(usage: dict[str, int]) -> dict[str, int]:
    prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", 0))
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": usage.get("total_tokens", prompt_tokens + completion_tokens),
    }

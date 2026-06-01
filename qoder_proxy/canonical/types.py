from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClientProtocol(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ContentBlockType(StrEnum):
    TEXT = "text"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class CanonicalToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class CanonicalToolResult(BaseModel):
    tool_call_id: str
    content: str
    is_error: bool = False


class CanonicalContentBlock(BaseModel):
    type: ContentBlockType
    text: str | None = None
    tool_call: CanonicalToolCall | None = None
    tool_result: CanonicalToolResult | None = None

    @classmethod
    def text_block(cls, text: str) -> "CanonicalContentBlock":
        return cls(type=ContentBlockType.TEXT, text=text)

    @classmethod
    def tool_call_block(cls, tool_call: CanonicalToolCall) -> "CanonicalContentBlock":
        return cls(type=ContentBlockType.TOOL_CALL, tool_call=tool_call)

    @classmethod
    def tool_result_block(cls, tool_result: CanonicalToolResult) -> "CanonicalContentBlock":
        return cls(type=ContentBlockType.TOOL_RESULT, tool_result=tool_result)


class CanonicalMessage(BaseModel):
    role: MessageRole
    content: list[CanonicalContentBlock] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GenerationOptions(BaseModel):
    max_tokens: int | None = Field(default=None, gt=0)
    temperature: float | None = Field(default=None, ge=0)
    top_p: float | None = Field(default=None, ge=0, le=1)
    stop_sequences: list[str] = Field(default_factory=list)


class ModelInfo(BaseModel):
    alias: str
    qoder_key: str
    qoder_source: str


class CanonicalRequest(BaseModel):
    model: str
    resolved_model: ModelInfo | None = None
    system: str | None = None
    messages: list[CanonicalMessage]
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: dict[str, Any] | str | None = None
    options: GenerationOptions = Field(default_factory=GenerationOptions)
    stream: bool = False
    client_protocol: ClientProtocol
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal[
        "response_start",
        "text_delta",
        "tool_call_delta",
        "response_metadata",
        "response_stop",
        "error",
    ]
    text: str | None = None
    tool_call: CanonicalToolCall | None = None
    finish_reason: str | None = None
    usage: dict[str, int] | None = None
    error: dict[str, Any] | None = None


class ToolCallAccumulator(BaseModel):
    calls: dict[str, CanonicalToolCall] = Field(default_factory=dict)

    def merge(
        self,
        tool_call_id: str,
        name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> CanonicalToolCall:
        existing = self.calls.get(tool_call_id)
        if existing is None:
            existing = CanonicalToolCall(id=tool_call_id, name=name or "", arguments={})
        merged_args = dict(existing.arguments)
        if arguments:
            merged_args.update(arguments)
        merged = CanonicalToolCall(
            id=tool_call_id,
            name=name if name is not None else existing.name,
            arguments=merged_args,
        )
        self.calls[tool_call_id] = merged
        return merged

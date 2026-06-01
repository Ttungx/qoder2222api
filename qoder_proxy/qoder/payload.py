import copy
import time
from typing import Any
from uuid import uuid4

from qoder_proxy.canonical.types import CanonicalRequest, ContentBlockType, MessageRole

BASE_PAYLOAD: dict[str, Any] = {
    "request_id": "",
    "request_set_id": "",
    "chat_record_id": "",
    "stream": True,
    "chat_task": "FREE_INPUT",
    "chat_context": {
        "chatPrompt": "",
        "extra": {
            "context": [],
            "modelConfig": {"is_reasoning": False, "key": "lite"},
            "originalContent": {"type": "text", "text": ""},
        },
        "features": [],
        "imageUrls": None,
        "text": {"type": "text", "text": ""},
    },
    "image_urls": None,
    "is_reply": True,
    "is_retry": False,
    "session_id": "",
    "code_language": "",
    "source": 1,
    "version": "3",
    "chat_prompt": "",
    "parameters": {"max_tokens": 32768},
    "aliyun_user_type": "personal_standard",
    "session_type": "qodercli",
    "agent_id": "agent_common",
    "task_id": "common",
    "model_config": {
        "key": "lite",
        "display_name": "Lite",
        "model": "",
        "format": "openai",
        "is_vl": False,
        "is_reasoning": False,
        "api_key": "",
        "url": "",
        "source": "system",
        "max_input_tokens": 180000,
    },
    "messages": [],
    "tools": [],
}


def build_qoder_payload(request: CanonicalRequest, *, user_type: str) -> dict[str, Any]:
    payload = copy.deepcopy(BASE_PAYLOAD)
    request_id = str(uuid4())
    payload["request_id"] = request_id
    payload["chat_record_id"] = request_id
    payload["request_set_id"] = str(uuid4())
    payload["session_id"] = str(uuid4())
    payload["stream"] = True
    payload["aliyun_user_type"] = user_type
    if request.options.max_tokens:
        payload["parameters"]["max_tokens"] = request.options.max_tokens

    model = request.resolved_model
    if model is not None:
        payload["model_config"]["key"] = model.qoder_key
        payload["model_config"]["source"] = model.qoder_source
        payload["chat_context"]["extra"]["modelConfig"]["key"] = model.qoder_key

    prompt = _latest_user_text(request)
    payload["chat_context"]["text"]["text"] = prompt
    payload["chat_context"]["extra"]["originalContent"]["text"] = prompt
    payload["business"] = {
        "id": str(uuid4()),
        "name": prompt[:30],
        "begin_at": int(time.time() * 1000),
    }
    payload["messages"] = [_message_to_qoder(message) for message in request.messages]
    if request.system:
        payload["messages"].insert(0, {"role": "system", "content": request.system, "contents": []})
    if request.tools:
        payload["tools"] = request.tools
    return payload


def _latest_user_text(request: CanonicalRequest) -> str:
    for message in reversed(request.messages):
        if message.role is MessageRole.USER:
            text = _message_text(message)
            if text:
                return text
    return ""


def _message_to_qoder(message: Any) -> dict[str, Any]:
    text = _message_text(message)
    return {
        "role": message.role.value,
        "content": text,
        "contents": [{"type": "text", "text": text}] if text else [],
    }


def _message_text(message: Any) -> str:
    parts: list[str] = []
    for block in message.content:
        if block.type is ContentBlockType.TEXT and block.text:
            parts.append(block.text)
        elif block.type is ContentBlockType.TOOL_RESULT and block.tool_result:
            parts.append(block.tool_result.content)
    return "\n".join(parts)

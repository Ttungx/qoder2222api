from collections.abc import AsyncIterator

from qoder_proxy.canonical.types import CanonicalEvent, CanonicalRequest


async def execute_mock(request: CanonicalRequest) -> AsyncIterator[CanonicalEvent]:
    yield CanonicalEvent(type="response_start")
    text = _mock_text(request)
    for chunk in _chunks(text):
        yield CanonicalEvent(type="text_delta", text=chunk)
    yield CanonicalEvent(
        type="response_metadata",
        usage={"input_tokens": 0, "output_tokens": len(text.split())},
    )
    yield CanonicalEvent(type="response_stop", finish_reason="end_turn")


def _mock_text(request: CanonicalRequest) -> str:
    last_text = ""
    for message in reversed(request.messages):
        for block in message.content:
            if block.text:
                last_text = block.text
                break
        if last_text:
            break
    return f"Mock Qoder response for {request.model}: {last_text or 'hello'}"


def _chunks(text: str) -> list[str]:
    words = text.split(" ")
    return [word if index == 0 else f" {word}" for index, word in enumerate(words)]

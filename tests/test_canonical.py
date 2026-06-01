from qoder_proxy.canonical import CanonicalContentBlock, CanonicalMessage, ErrorCode
from qoder_proxy.canonical.types import MessageRole, ToolCallAccumulator


def test_text_block_serializes() -> None:
    message = CanonicalMessage(
        role=MessageRole.USER,
        content=[CanonicalContentBlock.text_block("hello")],
    )

    assert message.model_dump(mode="json") == {
        "role": "user",
        "content": [
            {
                "type": "text",
                "text": "hello",
                "tool_call": None,
                "tool_result": None,
            }
        ],
        "metadata": {},
    }


def test_tool_call_accumulator_merges_arguments() -> None:
    accumulator = ToolCallAccumulator()

    accumulator.merge("toolu_1", name="read", arguments={"path": "a"})
    merged = accumulator.merge("toolu_1", arguments={"limit": 10})

    assert merged.name == "read"
    assert merged.arguments == {"path": "a", "limit": 10}


def test_error_codes_are_stable() -> None:
    assert ErrorCode.UNKNOWN_MODEL == "unknown_model"
    assert ErrorCode.STREAM_INTERRUPTED == "stream_interrupted"

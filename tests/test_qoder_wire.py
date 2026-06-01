import json
import time

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import (
    CanonicalContentBlock,
    CanonicalMessage,
    CanonicalRequest,
    ClientProtocol,
    MessageRole,
    ModelInfo,
)
from qoder_proxy.qoder.encoding import decode, encode
from qoder_proxy.qoder.payload import build_qoder_payload
from qoder_proxy.qoder.redaction import redact_sensitive
from qoder_proxy.qoder.signature import (
    compose_bearer,
    sign_center_request,
    sign_qoder_request,
)
from qoder_proxy.qoder.sse import parse_qoder_sse_data


def test_qoder_custom_encoding_round_trips_json_bytes() -> None:
    plain = b'{"hello":"world","n":1}'

    encoded = encode(plain)

    assert encoded != plain.decode()
    assert decode(encoded) == plain


def test_signature_helpers_match_known_md5_inputs() -> None:
    assert (
        sign_center_request("Mon, 01 Jun 2026 00:00:00 GMT")
        == "39cbdc58185c1d3e572284a5e70264af"
    )
    assert (
        sign_qoder_request("payload", "cosy", "123", "body", "/path")
        == "4e35ae52b97e137dc59319d5525ef7bf"
    )
    assert compose_bearer("payload", "sig") == "Bearer COSY.payload.sig"


def test_parse_qoder_sse_data_extracts_text_delta() -> None:
    inner = {"choices": [{"delta": {"content": "hello"}}]}
    wrapper = {"body": json.dumps(inner)}

    events = parse_qoder_sse_data(json.dumps(wrapper))

    assert len(events) == 1
    assert events[0].type == "text_delta"
    assert events[0].text == "hello"


def test_parse_qoder_sse_data_raises_stream_interrupted_on_malformed_json() -> None:
    try:
        parse_qoder_sse_data("not-json")
    except CanonicalError as error:
        assert error.code is ErrorCode.STREAM_INTERRUPTED
    else:
        raise AssertionError("expected CanonicalError")



def test_build_qoder_payload_sets_model_prompt_and_messages() -> None:
    request = CanonicalRequest(
        model="claude-sonnet-4-5",
        resolved_model=ModelInfo(
            alias="claude-sonnet-4-5",
            qoder_key="lite",
            qoder_source="system",
        ),
        messages=[
            CanonicalMessage(
                role=MessageRole.USER,
                content=[CanonicalContentBlock.text_block("hello qoder")],
            )
        ],
        stream=True,
        client_protocol=ClientProtocol.ANTHROPIC,
    )

    payload = build_qoder_payload(request, user_type="personal_standard")

    assert payload["stream"] is True
    assert payload["model_config"]["key"] == "lite"
    assert payload["model_config"]["source"] == "system"
    assert payload["chat_context"]["text"]["text"] == "hello qoder"
    assert abs(payload["business"]["begin_at"] - int(time.time() * 1000)) < 5000
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["content"] == "hello qoder"


def test_redact_sensitive_masks_known_secret_keys() -> None:
    value = {
        "personalToken": "pat-secret",
        "authorization": "Bearer COSY.payload.sig",
        "safe": "visible",
        "nested": {"machineToken": "machine-secret"},
    }

    redacted = redact_sensitive(value)

    assert redacted["personalToken"] == "pat-...cret"
    assert redacted["authorization"] == "Bear...sig"
    assert redacted["safe"] == "visible"
    assert redacted["nested"]["machineToken"] == "mach...cret"

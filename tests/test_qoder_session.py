import base64
import json

from qoder_proxy.qoder.session import (
    AuthIdentity,
    MachineIdentity,
    SessionBuilder,
    SessionContext,
)


def test_auth_payload_uses_qoder_field_names() -> None:
    identity = AuthIdentity(
        name="User",
        aid="aid-1",
        uid="uid-1",
        yx_uid="yx-1",
        organization_id="org-1",
        organization_name="Org",
        user_type="personal_standard",
        security_oauth_token="oauth-token",
        refresh_token="refresh-token",
    )

    payload = SessionBuilder.auth_payload_json(identity)

    assert json.loads(payload) == {
        "name": "User",
        "aid": "aid-1",
        "uid": "uid-1",
        "yx_uid": "yx-1",
        "organization_id": "org-1",
        "organization_name": "Org",
        "user_type": "personal_standard",
        "security_oauth_token": "oauth-token",
        "refresh_token": "refresh-token",
    }


def test_build_payload_b64_contains_sorted_qoder_payload_fields() -> None:
    payload_b64 = SessionBuilder.build_payload_b64("encrypted-info", request_id="req-1")

    decoded = json.loads(base64.b64decode(payload_b64).decode())

    assert list(decoded.keys()) == ["cosyVersion", "ideVersion", "info", "requestId", "version"]
    assert decoded["cosyVersion"] == "0.1.43"
    assert decoded["info"] == "encrypted-info"
    assert decoded["requestId"] == "req-1"
    assert decoded["version"] == "v1"


def test_build_session_context_contains_machine_and_identity() -> None:
    identity = AuthIdentity(name="User", aid="aid", uid="uid", user_type="personal_standard")
    machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")

    context = SessionBuilder.new_session(identity, machine, temp_key=b"1234567890abcdef")

    assert isinstance(context, SessionContext)
    assert context.identity.uid == "uid"
    assert context.machine.machine_id == "mid"
    assert context.info
    assert context.cosy_key
    assert context.temp_key == b"1234567890abcdef"

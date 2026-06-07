"""Diagnose why non-lite model keys cause peer closed connection."""
import asyncio
import json
import sys
import time
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from qoder_proxy.qoder.session import SessionBuilder, SessionContext, AuthIdentity, MachineIdentity
from qoder_proxy.qoder.encoding import encode
from qoder_proxy.qoder.signature import compose_bearer, sign_qoder_request
from qoder_proxy.qoder.payload import build_qoder_payload, BASE_PAYLOAD
from qoder_proxy.canonical.types import (
    CanonicalRequest, CanonicalMessage, ContentBlockType,
    MessageRole, ModelInfo, GenerationOptions,
)

import httpx
import copy

ACCOUNTS_PATH = Path(__file__).parent / "data" / "accounts.json"
API_BASE = "https://api3.qoder.sh"
GENERATION_PATH = (
    "/algo/api/v2/service/pro/sse/agent_chat_generation"
    "?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"
)


def load_account():
    data = json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))
    acct = data["accounts"][0]
    identity = AuthIdentity(**acct["identity"])
    machine = MachineIdentity(**acct["machine"])
    return identity, machine, acct["session_info"], acct["session_cosy_key"]


def build_headers(session, path, encoded_body, accept="text/event-stream"):
    from urllib.parse import urlsplit
    payload_b64 = SessionBuilder.build_payload_b64(session.info)
    cosy_date = str(int(time.time()))
    raw_path = urlsplit(path).path.removeprefix("/algo")
    signature = sign_qoder_request(payload_b64, session.cosy_key, cosy_date, encoded_body, raw_path)
    return {
        "cosy-data-policy": "AGREE",
        "content-type": "application/json",
        "cosy-machinetype": session.machine.machine_type,
        "cosy-clienttype": "5",
        "cosy-date": cosy_date,
        "cosy-user": session.identity.uid,
        "cosy-key": session.cosy_key,
        "accept": accept,
        "cosy-clientip": "169.254.198.161",
        "authorization": compose_bearer(payload_b64, signature),
        "accept-encoding": "identity",
        "cosy-version": "0.1.43",
        "cosy-machineid": session.machine.machine_id,
        "cosy-machinetoken": session.machine.machine_token,
        "login-version": "v2",
        "user-agent": "Go-http-client/2.0",
        "cache-control": "no-cache",
    }


def make_payload(model_key, model_source="system"):
    """Build a minimal payload for the given model key."""
    payload = copy.deepcopy(BASE_PAYLOAD)
    from uuid import uuid4
    rid = str(uuid4())
    payload["request_id"] = rid
    payload["chat_record_id"] = rid
    payload["request_set_id"] = str(uuid4())
    payload["session_id"] = str(uuid4())
    payload["stream"] = True
    payload["model_config"]["key"] = model_key
    payload["model_config"]["source"] = model_source
    payload["chat_context"]["extra"]["modelConfig"]["key"] = model_key
    payload["chat_context"]["text"]["text"] = "Say hello in one word"
    payload["chat_context"]["extra"]["originalContent"]["text"] = "Say hello in one word"
    payload["messages"] = [
        {"role": "user", "content": "Say hello in one word", "contents": [{"type": "text", "text": "Say hello in one word"}]}
    ]
    return payload


async def test_model_key(session, model_key, label=""):
    """Send a request and capture the full response."""
    print(f"\n{'='*60}")
    print(f"Testing model_key={model_key} {label}")
    print(f"{'='*60}")

    payload = make_payload(model_key)
    encoded_body = encode(json.dumps(payload, separators=(",", ":")).encode())
    headers = build_headers(session, GENERATION_PATH, encoded_body)
    headers["x-model-key"] = model_key
    headers["x-model-source"] = "system"

    url = f"{API_BASE}{GENERATION_PATH}"

    try:
        async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
            # First try non-streaming to get full response
            print(f"  [1] Non-streaming POST to {url[:80]}...")
            resp = await client.post(url, content=encoded_body, headers=headers)
            print(f"  Status: {resp.status_code}")
            print(f"  Headers: {dict(resp.headers)}")
            body_text = resp.text[:2000]
            print(f"  Body (first 2000 chars): {body_text}")
    except httpx.RemoteProtocolError as e:
        print(f"  [1] Non-streaming RemoteProtocolError: {e}")
        # Try streaming
        try:
            print(f"  [2] Trying streaming POST...")
            async with httpx.AsyncClient(timeout=60, trust_env=False) as client2:
                async with client2.stream("POST", url, content=encoded_body, headers=headers) as resp:
                    print(f"  Stream Status: {resp.status_code}")
                    print(f"  Stream Headers: {dict(resp.headers)}")
                    count = 0
                    async for line in resp.aiter_lines():
                        if count < 10:
                            print(f"  Line {count}: {line[:200]}")
                        count += 1
                    print(f"  Total lines: {count}")
        except httpx.RemoteProtocolError as e2:
            print(f"  [2] Streaming RemoteProtocolError: {e2}")
    except Exception as e:
        print(f"  Error: {type(e).__name__}: {e}")


async def main():
    identity, machine, sess_info, sess_cosy_key = load_account()
    print(f"Account: {identity.name}, user_type={identity.user_type}")
    print(f"UID: {identity.uid}")

    # Build a fresh session
    session = SessionBuilder.new_session(identity, machine)
    print(f"Fresh session created")

    # Test lite (known working)
    await test_model_key(session, "lite", "(known working)")

    # Test qmodel (known failing)
    await test_model_key(session, "qmodel", "(was failing)")

    # Test auto
    await test_model_key(session, "auto", "(auto-select)")


asyncio.run(main())

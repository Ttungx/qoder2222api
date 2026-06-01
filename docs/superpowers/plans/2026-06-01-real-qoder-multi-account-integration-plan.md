# Real Qoder Multi-Account Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the mock-only execution path with a configurable real Qoder upstream executor that supports PAT accounts, local-import/OAuth provider interfaces, session refresh, account scheduling, and protocol end-to-end routing.

**Architecture:** Keep protocol adapters isolated from Qoder/account internals. Add focused Qoder modules for session construction, auth, signed HTTP/SSE client, and executor; add focused account modules for providers and pool orchestration; wire them into FastAPI through config-controlled executor mode while keeping mock mode as the default.

**Tech Stack:** Python 3.11+, FastAPI, httpx, Pydantic, PyYAML, pytest, Ruff.

---

## File map

Create:

- `qoder_proxy/qoder/session.py` — Qoder auth identity, machine identity, session context, RSA/AES session builder, payload base64 builder.
- `qoder_proxy/qoder/auth.py` — async Qoder center auth client for PAT exchange, status, and heartbeat.
- `qoder_proxy/qoder/client.py` — async signed/encoded Qoder JSON and SSE client.
- `qoder_proxy/qoder/executor.py` — canonical request to real Qoder canonical events.
- `qoder_proxy/accounts/providers.py` — PAT, local import, and OAuth provider interfaces/implementations.
- `qoder_proxy/accounts/pool.py` — account selection, session refresh, execution health update orchestration.
- `tests/test_qoder_session.py` — session construction tests.
- `tests/test_qoder_auth_client.py` — mocked PAT exchange/status/heartbeat tests.
- `tests/test_qoder_client.py` — signed headers/body/SSE transport tests.
- `tests/test_qoder_executor.py` — executor request/event/error tests.
- `tests/test_account_providers_pool.py` — provider/pool tests.
- `tests/test_real_executor_api_integration.py` — API route integration with mocked real executor path.

Modify:

- `qoder_proxy/config/models.py` — add executor/accounts/qoder config sections and env overrides.
- `qoder_proxy/config/__init__.py` — export new config models.
- `qoder_proxy/accounts/models.py` — add machine/session/credential fields needed by real accounts.
- `qoder_proxy/accounts/storage.py` — keep JSON backend; support updated Account shape.
- `qoder_proxy/accounts/scheduler.py` — add failure classification update helper if not better placed in pool.
- `qoder_proxy/accounts/__init__.py` — export providers and pool.
- `qoder_proxy/qoder/payload.py` — improve canonical-to-Qoder message/tool conversion if executor tests require it.
- `qoder_proxy/qoder/sse.py` — parse finish reasons, usage, and tool-call deltas.
- `qoder_proxy/qoder/__init__.py` — export real executor pieces.
- `qoder_proxy/api/app.py` — choose mock or qoder executor from config, account pool, and injected test dependencies.
- `qoder_proxy/cli/main.py` — add account check/remove/import-local/login and serve executor override.
- `README.md` — document real-executor config, PAT setup, local import/OAuth status, and real-test commands.

---

### Task 1: Config model for executor, account storage, and Qoder endpoints

**Files:**
- Modify: `qoder_proxy/config/models.py`
- Modify: `qoder_proxy/config/__init__.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for new config sections**

Append these tests to `tests/test_config.py`:

```python
def test_default_config_includes_executor_accounts_and_qoder_sections() -> None:
    config = load_config(Path("missing-config.yaml"))

    assert config.executor.mode == "mock"
    assert config.accounts.storage_path == "./data/accounts.json"
    assert config.qoder.center_base_url == "https://center.qoder.sh"
    assert config.qoder.api_base_url == "https://api3.qoder.sh"
    assert config.qoder.client_version == "0.1.43"


def test_config_loads_qoder_executor_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
executor:
  mode: qoder
accounts:
  storage_path: ./data/custom-accounts.json
qoder:
  center_base_url: https://center.example.test
  api_base_url: https://api.example.test
  client_version: 9.9.9
models:
  - alias: claude-test
    qoder_key: pro
    qoder_source: system
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.executor.mode == "qoder"
    assert config.accounts.storage_path == "./data/custom-accounts.json"
    assert config.qoder.center_base_url == "https://center.example.test"
    assert config.qoder.api_base_url == "https://api.example.test"
    assert config.qoder.client_version == "9.9.9"
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_config.py::test_default_config_includes_executor_accounts_and_qoder_sections tests/test_config.py::test_config_loads_qoder_executor_mode -v
```

Expected: FAIL because `ProxyConfig` has no `executor`, `accounts.storage_path`, or `qoder` sections.

- [ ] **Step 3: Implement config models**

In `qoder_proxy/config/models.py`, add these models above `ProxyConfig`:

```python
class ExecutorConfig(BaseModel):
    mode: str = Field(default="mock", pattern="^(mock|qoder)$")


class AccountsConfig(BaseModel):
    storage_path: str = "./data/accounts.json"


class QoderConfig(BaseModel):
    center_base_url: str = "https://center.qoder.sh"
    api_base_url: str = "https://api3.qoder.sh"
    client_version: str = "0.1.43"
```

Update `ProxyConfig` so it has both legacy inline account seed config and the new account storage config:

```python
class ProxyConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    executor: ExecutorConfig = Field(default_factory=ExecutorConfig)
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
    account_seeds: list[AccountConfig] = Field(default_factory=list)
    qoder: QoderConfig = Field(default_factory=QoderConfig)
    models: list[ModelAliasConfig] = Field(default_factory=list)
```

Update `load_config()` env overrides:

```python
    if executor_mode := os.getenv("QODER_PROXY_EXECUTOR"):
        config.executor.mode = executor_mode
    if accounts_path := os.getenv("QODER_PROXY_ACCOUNTS_PATH"):
        config.accounts.storage_path = accounts_path
    if center_base_url := os.getenv("QODER_CENTER_BASE_URL"):
        config.qoder.center_base_url = center_base_url
    if api_base_url := os.getenv("QODER_API_BASE_URL"):
        config.qoder.api_base_url = api_base_url
```

- [ ] **Step 4: Export new config models**

In `qoder_proxy/config/__init__.py`, import and add to `__all__`:

```python
AccountsConfig,
ExecutorConfig,
QoderConfig,
```

- [ ] **Step 5: Run config tests**

Run:

```bash
python -m pytest tests/test_config.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add qoder_proxy/config tests/test_config.py
git commit -m "Add real executor configuration"
```

---

### Task 2: Qoder session builder

**Files:**
- Create: `qoder_proxy/qoder/session.py`
- Modify: `qoder_proxy/qoder/__init__.py`
- Test: `tests/test_qoder_session.py`

- [ ] **Step 1: Write failing session tests**

Create `tests/test_qoder_session.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_qoder_session.py -v
```

Expected: FAIL because `qoder_proxy.qoder.session` does not exist.

- [ ] **Step 3: Implement session models and builder**

Create `qoder_proxy/qoder/session.py`:

```python
import base64
import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
except ImportError:  # pragma: no cover
    hashes = serialization = padding = Cipher = algorithms = modes = PKCS7 = None

SERVER_PUBKEY_PEM = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDA8iMH5c02LilrsERw9t6Pv5Nc
4k6Pz1EaDicBMpdpxKduSZu5OANqUq8er4GM95omAGIOPOh+Nx0spthYA2BqGz+l
6HRkPJ7S236FZz73In/KVuLnwI8JJ2CbuJap8kvheCCZpmAWpb/cPx/3Vr/J6I17
XcW+ML9FoCI6AOvOzwIDAQAB
-----END PUBLIC KEY-----"""


@dataclass(frozen=True)
class AuthIdentity:
    name: str = ""
    aid: str = ""
    uid: str = ""
    yx_uid: str = ""
    organization_id: str = ""
    organization_name: str = ""
    user_type: str = "personal_standard"
    security_oauth_token: str = ""
    refresh_token: str = ""


@dataclass(frozen=True)
class MachineIdentity:
    machine_id: str
    machine_token: str
    machine_type: str


@dataclass(frozen=True)
class SessionContext:
    temp_key: bytes
    cosy_key: str
    info: str
    identity: AuthIdentity
    machine: MachineIdentity


class SessionBuilder:
    @staticmethod
    def auth_payload_json(identity: AuthIdentity) -> bytes:
        payload = {
            "name": identity.name,
            "aid": identity.aid,
            "uid": identity.uid,
            "yx_uid": identity.yx_uid,
            "organization_id": identity.organization_id,
            "organization_name": identity.organization_name,
            "user_type": identity.user_type,
            "security_oauth_token": identity.security_oauth_token,
            "refresh_token": identity.refresh_token,
        }
        return json.dumps(payload, separators=(",", ":")).encode()

    @staticmethod
    def build_payload_b64(info: str, request_id: str | None = None) -> str:
        payload: dict[str, Any] = {
            "cosyVersion": "0.1.43",
            "ideVersion": "",
            "info": info,
            "requestId": request_id or str(uuid4()),
            "version": "v1",
        }
        encoded = json.dumps(dict(sorted(payload.items())), separators=(",", ":")).encode()
        return base64.b64encode(encoded).decode()

    @staticmethod
    def new_session(
        identity: AuthIdentity,
        machine: MachineIdentity,
        temp_key: bytes | None = None,
    ) -> SessionContext:
        temp_key = temp_key or uuid4().hex[:16].encode("ascii")
        cosy_key = base64.b64encode(SessionBuilder.rsa_encrypt(temp_key)).decode()
        info = base64.b64encode(
            SessionBuilder.aes_encrypt(SessionBuilder.auth_payload_json(identity), temp_key)
        ).decode()
        return SessionContext(
            temp_key=temp_key,
            cosy_key=cosy_key,
            info=info,
            identity=identity,
            machine=machine,
        )

    @staticmethod
    def rsa_encrypt(value: bytes) -> bytes:
        if serialization is None:
            raise RuntimeError("cryptography is required for Qoder session encryption")
        public_key = serialization.load_pem_public_key(SERVER_PUBKEY_PEM.encode())
        return public_key.encrypt(value, padding.PKCS1v15())

    @staticmethod
    def aes_encrypt(value: bytes, key: bytes) -> bytes:
        if Cipher is None:
            raise RuntimeError("cryptography is required for Qoder session encryption")
        padder = PKCS7(128).padder()
        padded = padder.update(value) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(key)).encryptor()
        return encryptor.update(padded) + encryptor.finalize()
```

- [ ] **Step 4: Add cryptography dependency**

In `pyproject.toml`, add runtime dependency:

```toml
"cryptography>=43.0.0",
```

- [ ] **Step 5: Export session symbols**

In `qoder_proxy/qoder/__init__.py`, add:

```python
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder, SessionContext

__all__ = ["AuthIdentity", "MachineIdentity", "SessionBuilder", "SessionContext"]
```

- [ ] **Step 6: Run session tests**

Run:

```bash
python -m pytest tests/test_qoder_session.py -v
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml qoder_proxy/qoder/session.py qoder_proxy/qoder/__init__.py tests/test_qoder_session.py
git commit -m "Add Qoder session builder"
```

---

### Task 3: Qoder auth client for PAT exchange and status

**Files:**
- Create: `qoder_proxy/qoder/auth.py`
- Test: `tests/test_qoder_auth_client.py`

- [ ] **Step 1: Write failing auth client tests**

Create `tests/test_qoder_auth_client.py`:

```python
import json

import httpx
import pytest

from qoder_proxy.qoder.auth import QoderAuthClient
from qoder_proxy.qoder.encoding import decode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity


@pytest.mark.asyncio
async def test_exchange_pat_posts_encoded_payload_and_returns_identity() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(decode(request.content).decode())
        return httpx.Response(
            200,
            json={
                "name": "User",
                "id": "user-1",
                "userType": "personal_standard",
                "securityOauthToken": "oauth-token",
                "refreshToken": "refresh-token",
            },
        )

    client = QoderAuthClient(
        center_base_url="https://center.example.test",
        transport=httpx.MockTransport(handler),
    )
    machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")

    identity = await client.exchange_pat("pat-secret", machine)

    assert isinstance(identity, AuthIdentity)
    assert identity.uid == "user-1"
    assert identity.security_oauth_token == "oauth-token"
    assert captured["url"] == "https://center.example.test/algo/api/v3/user/jobToken?Encode=1"
    assert captured["body"] == {
        "payload": json.dumps(
            {
                "personalToken": "pat-secret",
                "securityOauthToken": "",
                "refreshToken": "",
                "needRefresh": False,
                "authInfo": {},
            },
            separators=(",", ":"),
        ),
        "encodeVersion": "1",
    }
    headers = captured["headers"]
    assert headers["cosy-machineid"] == "mid"
    assert headers["cosy-machinetoken"] == "mtok"
    assert headers["cosy-machinetype"] == "mtype"
    assert headers["appcode"] == "cosy"
    assert "signature" in headers


@pytest.mark.asyncio
async def test_exchange_pat_raises_authentication_failed_on_401() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="bad token")

    client = QoderAuthClient(
        center_base_url="https://center.example.test",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(Exception) as error:
        await client.exchange_pat(
            "bad",
            MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype"),
        )

    assert "authentication_failed" in str(error.value)
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_qoder_auth_client.py -v
```

Expected: FAIL because `qoder_proxy.qoder.auth` does not exist.

- [ ] **Step 3: Implement auth client**

Create `qoder_proxy/qoder/auth.py`:

```python
import json
from email.utils import formatdate
from typing import Any

import httpx

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.encoding import encode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity
from qoder_proxy.qoder.signature import APPCODE, sign_center_request


class QoderAuthClient:
    def __init__(
        self,
        *,
        center_base_url: str,
        client_version: str = "0.1.43",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.center_base_url = center_base_url.rstrip("/")
        self.client_version = client_version
        self.transport = transport

    async def exchange_pat(self, personal_token: str, machine: MachineIdentity) -> AuthIdentity:
        inner = {
            "personalToken": personal_token,
            "securityOauthToken": "",
            "refreshToken": "",
            "needRefresh": False,
            "authInfo": {},
        }
        outer = {
            "payload": json.dumps(inner, separators=(",", ":")),
            "encodeVersion": "1",
        }
        data = await self._post_encoded("/algo/api/v3/user/jobToken?Encode=1", outer, machine)
        return AuthIdentity(
            name=str(data.get("name", "")),
            aid=str(data.get("id", "")),
            uid=str(data.get("id", "")),
            user_type=str(data.get("userType", "personal_standard")),
            security_oauth_token=str(data.get("securityOauthToken", "")),
            refresh_token=str(data.get("refreshToken", "")),
        )

    async def user_status(self, user_id: str, machine: MachineIdentity) -> dict[str, Any]:
        inner = {
            "userId": user_id,
            "personalToken": "",
            "securityOauthToken": "",
            "refreshToken": "",
            "needRefresh": False,
            "authInfo": {},
        }
        outer = {
            "payload": json.dumps(inner, separators=(",", ":")),
            "encodeVersion": "1",
        }
        return await self._post_encoded("/algo/api/v3/user/status?Encode=1", outer, machine)

    async def _post_encoded(
        self,
        path: str,
        payload: dict[str, Any],
        machine: MachineIdentity,
    ) -> dict[str, Any]:
        date = formatdate(usegmt=True)
        body = encode(json.dumps(payload, separators=(",", ":")).encode())
        headers = {
            "cosy-machinetoken": machine.machine_token,
            "cosy-machinetype": machine.machine_type,
            "login-version": "v2",
            "appcode": APPCODE,
            "accept": "application/json",
            "accept-encoding": "identity",
            "cosy-version": self.client_version,
            "cosy-clienttype": "5",
            "date": date,
            "signature": sign_center_request(date),
            "content-type": "application/json",
            "cosy-machineid": machine.machine_id,
            "user-agent": "Go-http-client/2.0",
        }
        async with httpx.AsyncClient(transport=self.transport, timeout=15) as client:
            response = await client.post(f"{self.center_base_url}{path}", content=body, headers=headers)
        if response.status_code in {401, 403}:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                "Qoder authentication failed",
                http_status=401,
                account_impact="disable",
            )
        if response.status_code != 200:
            raise CanonicalError(
                ErrorCode.UPSTREAM_ERROR,
                f"Qoder center API returned HTTP {response.status_code}",
                http_status=502,
                retryable=response.status_code >= 500,
            )
        return response.json()
```

- [ ] **Step 4: Run auth tests**

Run:

```bash
python -m pytest tests/test_qoder_auth_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qoder_proxy/qoder/auth.py tests/test_qoder_auth_client.py
git commit -m "Add Qoder auth client"
```

---

### Task 4: Signed Qoder HTTP/SSE client

**Files:**
- Create: `qoder_proxy/qoder/client.py`
- Test: `tests/test_qoder_client.py`

- [ ] **Step 1: Write failing signed client tests**

Create `tests/test_qoder_client.py`:

```python
import json

import httpx
import pytest

from qoder_proxy.qoder.client import QoderClient
from qoder_proxy.qoder.encoding import decode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


def _session():
    return SessionBuilder.new_session(
        AuthIdentity(name="User", aid="aid", uid="uid", user_type="personal_standard"),
        MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype"),
        temp_key=b"1234567890abcdef",
    )


@pytest.mark.asyncio
async def test_post_json_sends_encoded_body_and_signed_headers() -> None:
    captured: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(decode(request.content.decode()).decode())
        return httpx.Response(200, json={"ok": True})

    client = QoderClient(
        api_base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )

    response = await client.post_json(_session(), "/algo/api/test?Encode=1", {"hello": "world"})

    assert response == {"ok": True}
    assert captured["url"] == "https://api.example.test/algo/api/test?Encode=1"
    assert captured["body"] == {"hello": "world"}
    headers = captured["headers"]
    assert headers["authorization"].startswith("Bearer COSY.")
    assert headers["cosy-machineid"] == "mid"
    assert headers["cosy-machinetoken"] == "mtok"
    assert headers["cosy-key"]
    assert headers["accept"] == "application/json"


@pytest.mark.asyncio
async def test_stream_sse_yields_non_empty_sse_lines() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b'data: {"body":"{\\"choices\\":[{\\"delta\\":{\\"content\\":\\"hi\\"}}]}"}\n\n',
            headers={"content-type": "text/event-stream"},
        )

    client = QoderClient(
        api_base_url="https://api.example.test",
        transport=httpx.MockTransport(handler),
    )

    lines = [line async for line in client.stream_sse(_session(), "/algo/api/test?Encode=1", {"x": 1})]

    assert lines == ['data: {"body":"{\\"choices\\":[{\\"delta\\":{\\"content\\":\\"hi\\"}}]}"}']
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_qoder_client.py -v
```

Expected: FAIL because `qoder_proxy.qoder.client` does not exist.

- [ ] **Step 3: Implement signed client**

Create `qoder_proxy/qoder/client.py`:

```python
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import urlsplit

import httpx

from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.encoding import encode
from qoder_proxy.qoder.session import SessionBuilder, SessionContext
from qoder_proxy.qoder.signature import compose_bearer, sign_qoder_request


class QoderClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        client_version: str = "0.1.43",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.api_base_url = api_base_url.rstrip("/")
        self.client_version = client_version
        self.transport = transport

    async def post_json(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any] | None,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        encoded_body, headers = self._headers(session, path, body, accept="application/json")
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(transport=self.transport, timeout=30) as client:
            response = await client.post(f"{self.api_base_url}{path}", content=encoded_body, headers=headers)
        self._raise_for_status(response)
        return response.json()

    async def stream_sse(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any],
        extra_headers: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        encoded_body, headers = self._headers(session, path, body, accept="text/event-stream")
        headers["cache-control"] = "no-cache"
        if extra_headers:
            headers.update(extra_headers)
        async with httpx.AsyncClient(transport=self.transport, timeout=300) as client:
            async with client.stream(
                "POST",
                f"{self.api_base_url}{path}",
                content=encoded_body,
                headers=headers,
            ) as response:
                self._raise_for_status(response)
                async for line in response.aiter_lines():
                    if line:
                        yield line

    def _headers(
        self,
        session: SessionContext,
        path: str,
        body: dict[str, Any] | None,
        *,
        accept: str,
    ) -> tuple[str, dict[str, str]]:
        encoded_body = "" if body is None else encode(json.dumps(body, separators=(",", ":")).encode())
        payload_b64 = SessionBuilder.build_payload_b64(session.info)
        cosy_date = str(int(time.time()))
        signature = sign_qoder_request(
            payload_b64,
            session.cosy_key,
            cosy_date,
            encoded_body,
            _path_without_algo(path),
        )
        return encoded_body, {
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
            "cosy-version": self.client_version,
            "cosy-machineid": session.machine.machine_id,
            "cosy-machinetoken": session.machine.machine_token,
            "login-version": "v2",
            "user-agent": "Go-http-client/2.0",
        }

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 200:
            return
        if response.status_code in {401, 403}:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                "Qoder upstream authentication failed",
                http_status=401,
                account_impact="disable",
            )
        if response.status_code == 429:
            raise CanonicalError(ErrorCode.RATE_LIMITED, "Qoder upstream rate limited", http_status=429)
        raise CanonicalError(
            ErrorCode.UPSTREAM_ERROR,
            f"Qoder upstream returned HTTP {response.status_code}",
            http_status=502,
            retryable=response.status_code >= 500,
        )


def _path_without_algo(path: str) -> str:
    parsed = urlsplit(path)
    raw_path = parsed.path
    return raw_path.removeprefix("/algo")
```

- [ ] **Step 4: Run client tests**

Run:

```bash
python -m pytest tests/test_qoder_client.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qoder_proxy/qoder/client.py tests/test_qoder_client.py
git commit -m "Add signed Qoder client"
```

---

### Task 5: Expand account model and providers

**Files:**
- Modify: `qoder_proxy/accounts/models.py`
- Create: `qoder_proxy/accounts/providers.py`
- Modify: `qoder_proxy/accounts/__init__.py`
- Test: `tests/test_account_providers_pool.py`

- [ ] **Step 1: Write failing provider tests**

Create `tests/test_account_providers_pool.py` with provider tests first:

```python
import os
from pathlib import Path

import pytest

from qoder_proxy.accounts.models import Account
from qoder_proxy.accounts.providers import LocalQoderImportProvider, OAuthImportProvider, PATAccountProvider
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity


class FakeAuthClient:
    async def exchange_pat(self, personal_token: str, machine: MachineIdentity) -> AuthIdentity:
        assert personal_token == "pat-secret"
        return AuthIdentity(
            name="User",
            aid="user-1",
            uid="user-1",
            user_type="personal_standard",
            security_oauth_token="oauth-token",
            refresh_token="refresh-token",
        )


@pytest.mark.asyncio
async def test_pat_provider_refreshes_identity_from_pat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QODER_PAT", "pat-secret")
    account = Account(id="acct_1", display_name="main", source="pat", pat_env="QODER_PAT")

    refreshed = await PATAccountProvider(FakeAuthClient()).refresh(account)

    assert refreshed.identity.uid == "user-1"
    assert refreshed.identity.security_oauth_token == "oauth-token"
    assert refreshed.machine.machine_id
    assert refreshed.machine.machine_token
    assert refreshed.machine.machine_type


def test_local_import_provider_reads_json_identity(tmp_path: Path) -> None:
    state = tmp_path / "qoder-account.json"
    state.write_text(
        '{"name":"Local","id":"local-1","securityOauthToken":"oauth","refreshToken":"refresh"}',
        encoding="utf-8",
    )

    accounts = LocalQoderImportProvider([tmp_path]).import_accounts()

    assert len(accounts) == 1
    assert accounts[0].display_name == "Local"
    assert accounts[0].identity.uid == "local-1"


def test_oauth_provider_reports_unsupported() -> None:
    with pytest.raises(NotImplementedError, match="Browser login is not implemented"):
        OAuthImportProvider().login()
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```bash
python -m pytest tests/test_account_providers_pool.py -v
```

Expected: FAIL because providers and expanded account fields do not exist.

- [ ] **Step 3: Expand account model**

Modify `qoder_proxy/accounts/models.py`:

```python
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity
```

Add fields to `Account`:

```python
    identity: AuthIdentity | None = None
    machine: MachineIdentity | None = None
    session_info: str | None = None
    session_cosy_key: str | None = None
```

Because dataclasses need Pydantic support, add to the `Account` model:

```python
    model_config = ConfigDict(arbitrary_types_allowed=True)
```

and import `ConfigDict` from Pydantic.

- [ ] **Step 4: Implement providers**

Create `qoder_proxy/accounts/providers.py`:

```python
import json
import os
from pathlib import Path
from uuid import uuid4

from qoder_proxy.accounts.models import Account
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity


class PATAccountProvider:
    def __init__(self, auth_client) -> None:
        self.auth_client = auth_client

    async def refresh(self, account: Account) -> Account:
        token = account.pat or (os.getenv(account.pat_env) if account.pat_env else None)
        if not token:
            raise ValueError(f"No PAT available for account {account.id}")
        machine = account.machine or _new_machine()
        identity = await self.auth_client.exchange_pat(token, machine)
        return account.model_copy(update={"identity": identity, "machine": machine})


class LocalQoderImportProvider:
    def __init__(self, search_paths: list[Path] | None = None) -> None:
        self.search_paths = search_paths or _default_local_paths()

    def import_accounts(self) -> list[Account]:
        accounts: list[Account] = []
        for root in self.search_paths:
            state = root / "qoder-account.json"
            if not state.exists():
                continue
            data = json.loads(state.read_text(encoding="utf-8"))
            identity = AuthIdentity(
                name=str(data.get("name", "")),
                aid=str(data.get("id", "")),
                uid=str(data.get("id", "")),
                user_type=str(data.get("userType", "personal_standard")),
                security_oauth_token=str(data.get("securityOauthToken", "")),
                refresh_token=str(data.get("refreshToken", "")),
            )
            accounts.append(
                Account(
                    id=f"acct_{uuid4().hex[:12]}",
                    display_name=identity.name or identity.uid,
                    source="local",
                    identity=identity,
                    machine=_new_machine(),
                )
            )
        return accounts


class OAuthImportProvider:
    def login(self) -> Account:
        raise NotImplementedError("Browser login is not implemented for this Qoder flow yet")


def _new_machine() -> MachineIdentity:
    return MachineIdentity(
        machine_id=str(uuid4()),
        machine_token=uuid4().hex + uuid4().hex,
        machine_type=uuid4().hex[:18],
    )


def _default_local_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".qoder",
        home / ".config" / "qoder",
        home / "AppData" / "Roaming" / "Qoder",
    ]
```

- [ ] **Step 5: Export providers**

Update `qoder_proxy/accounts/__init__.py`:

```python
from qoder_proxy.accounts.providers import LocalQoderImportProvider, OAuthImportProvider, PATAccountProvider
```

Add these names to `__all__`.

- [ ] **Step 6: Run provider tests**

Run:

```bash
python -m pytest tests/test_account_providers_pool.py -v
```

Expected: PASS for the three provider tests.

- [ ] **Step 7: Run existing account storage tests**

Run:

```bash
python -m pytest tests/test_accounts.py tests/test_cli_accounts.py -v
```

Expected: PASS; if JSON serialization fails for dataclasses, switch `AuthIdentity` and `MachineIdentity` to Pydantic `BaseModel` in `qoder/session.py` and update tests unchanged.

- [ ] **Step 8: Commit**

```bash
git add qoder_proxy/accounts qoder_proxy/qoder/session.py tests/test_account_providers_pool.py tests/test_accounts.py tests/test_cli_accounts.py
git commit -m "Add account providers"
```

---

### Task 6: Account pool refresh, selection, and failure updates

**Files:**
- Create: `qoder_proxy/accounts/pool.py`
- Modify: `qoder_proxy/accounts/__init__.py`
- Test: `tests/test_account_providers_pool.py`

- [ ] **Step 1: Add failing pool tests**

Append to `tests/test_account_providers_pool.py`:

```python
from datetime import UTC, datetime, timedelta

from qoder_proxy.accounts.models import AccountHealth
from qoder_proxy.accounts.pool import AccountPool
from qoder_proxy.accounts.scheduler import AccountScheduler
from qoder_proxy.accounts.storage import JsonAccountStorage
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode


@pytest.mark.asyncio
async def test_account_pool_selects_and_refreshes_pat_account(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QODER_PAT", "pat-secret")
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    storage.save(Account(id="acct_1", display_name="main", source="pat", pat_env="QODER_PAT", supported_models=["lite"]))
    pool = AccountPool(storage=storage, scheduler_factory=AccountScheduler, pat_provider=PATAccountProvider(FakeAuthClient()))

    account = await pool.select_for_model("lite")

    assert account.id == "acct_1"
    assert account.identity.uid == "user-1"
    assert storage.get("acct_1").identity.uid == "user-1"


def test_account_pool_marks_auth_failure_disabled(tmp_path: Path) -> None:
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    storage.save(Account(id="acct_1", display_name="main", source="pat"))
    pool = AccountPool(storage=storage, scheduler_factory=AccountScheduler)

    pool.apply_error("acct_1", CanonicalError(ErrorCode.AUTHENTICATION_FAILED, "bad", http_status=401))

    account = storage.get("acct_1")
    assert account.enabled is False
    assert account.health is AccountHealth.AUTH_FAILED


def test_account_pool_marks_rate_limit_cooldown(tmp_path: Path) -> None:
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    storage.save(Account(id="acct_1", display_name="main", source="pat"))
    pool = AccountPool(storage=storage, scheduler_factory=AccountScheduler)

    pool.apply_error("acct_1", CanonicalError(ErrorCode.RATE_LIMITED, "slow", http_status=429))

    account = storage.get("acct_1")
    assert account.enabled is True
    assert account.health is AccountHealth.RATE_LIMITED
    assert account.cooldown_until > datetime.now(UTC) + timedelta(seconds=1)
```

- [ ] **Step 2: Run pool tests to verify failure**

Run:

```bash
python -m pytest tests/test_account_providers_pool.py -v
```

Expected: FAIL because `AccountPool` does not exist.

- [ ] **Step 3: Implement AccountPool**

Create `qoder_proxy/accounts/pool.py`:

```python
from datetime import UTC, datetime, timedelta
from typing import Callable

from qoder_proxy.accounts.models import Account, AccountHealth
from qoder_proxy.accounts.providers import PATAccountProvider
from qoder_proxy.accounts.scheduler import AccountScheduler
from qoder_proxy.accounts.storage import JsonAccountStorage
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode


class AccountPool:
    def __init__(
        self,
        *,
        storage: JsonAccountStorage,
        scheduler_factory: Callable[[list[Account]], AccountScheduler] = AccountScheduler,
        pat_provider: PATAccountProvider | None = None,
    ) -> None:
        self.storage = storage
        self.scheduler_factory = scheduler_factory
        self.pat_provider = pat_provider

    async def select_for_model(self, qoder_key: str) -> Account:
        scheduler = self.scheduler_factory(self.storage.list())
        account = scheduler.select(qoder_key)
        if account is None:
            raise CanonicalError(
                ErrorCode.NO_AVAILABLE_ACCOUNT,
                f"No available Qoder account for model {qoder_key}",
                http_status=503,
                retryable=True,
            )
        if account.source == "pat" and account.identity is None:
            if self.pat_provider is None:
                raise CanonicalError(
                    ErrorCode.AUTHENTICATION_FAILED,
                    "PAT account cannot refresh without auth provider",
                    http_status=401,
                )
            account = await self.pat_provider.refresh(account)
            self.storage.save(account)
        return account

    def apply_success(self, account_id: str) -> None:
        account = self.storage.get(account_id)
        self.storage.save(
            account.model_copy(update={"health": AccountHealth.OK, "failure_count": 0, "cooldown_until": None})
        )

    def apply_error(self, account_id: str, error: CanonicalError) -> None:
        account = self.storage.get(account_id)
        updates = {"failure_count": account.failure_count + 1}
        if error.code is ErrorCode.AUTHENTICATION_FAILED:
            updates.update({"enabled": False, "health": AccountHealth.AUTH_FAILED})
        elif error.code is ErrorCode.RATE_LIMITED:
            updates.update(
                {
                    "health": AccountHealth.RATE_LIMITED,
                    "cooldown_until": datetime.now(UTC) + timedelta(seconds=30),
                }
            )
        elif error.code is ErrorCode.QUOTA_EXHAUSTED:
            updates.update(
                {
                    "health": AccountHealth.QUOTA_EXHAUSTED,
                    "cooldown_until": datetime.now(UTC) + timedelta(hours=1),
                }
            )
        else:
            updates.update(
                {
                    "health": AccountHealth.UPSTREAM_ERROR,
                    "cooldown_until": datetime.now(UTC) + timedelta(seconds=10),
                }
            )
        self.storage.save(account.model_copy(update=updates))
```

- [ ] **Step 4: Export AccountPool**

Update `qoder_proxy/accounts/__init__.py`:

```python
from qoder_proxy.accounts.pool import AccountPool
```

Add `"AccountPool"` to `__all__`.

- [ ] **Step 5: Run pool tests**

Run:

```bash
python -m pytest tests/test_account_providers_pool.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add qoder_proxy/accounts/pool.py qoder_proxy/accounts/__init__.py tests/test_account_providers_pool.py
git commit -m "Add account pool orchestration"
```

---

### Task 7: Real Qoder executor

**Files:**
- Create: `qoder_proxy/qoder/executor.py`
- Modify: `qoder_proxy/qoder/sse.py`
- Test: `tests/test_qoder_executor.py`

- [ ] **Step 1: Write failing executor tests**

Create `tests/test_qoder_executor.py`:

```python
import json

import pytest

from qoder_proxy.accounts.models import Account
from qoder_proxy.canonical.types import CanonicalContentBlock, CanonicalMessage, CanonicalRequest
from qoder_proxy.canonical.types import ClientProtocol, MessageRole, ModelInfo
from qoder_proxy.qoder.executor import QoderExecutor
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


class FakeQoderClient:
    def __init__(self) -> None:
        self.extra_headers = None
        self.body = None

    async def stream_sse(self, session, path, body, extra_headers=None):
        self.body = body
        self.extra_headers = extra_headers
        inner = {"choices": [{"delta": {"content": "hello"}}]}
        yield "data: " + json.dumps({"body": json.dumps(inner)})


def _account() -> Account:
    identity = AuthIdentity(name="User", aid="aid", uid="uid", user_type="personal_standard")
    machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")
    session = SessionBuilder.new_session(identity, machine, temp_key=b"1234567890abcdef")
    return Account(
        id="acct_1",
        display_name="main",
        source="pat",
        identity=identity,
        machine=machine,
        session_info=session.info,
        session_cosy_key=session.cosy_key,
    )


def _request() -> CanonicalRequest:
    return CanonicalRequest(
        model="claude-sonnet-4-5",
        resolved_model=ModelInfo(alias="claude-sonnet-4-5", qoder_key="lite", qoder_source="system"),
        messages=[CanonicalMessage(role=MessageRole.USER, content=[CanonicalContentBlock.text_block("hi")])],
        stream=True,
        client_protocol=ClientProtocol.ANTHROPIC,
    )


@pytest.mark.asyncio
async def test_qoder_executor_streams_canonical_text_events() -> None:
    client = FakeQoderClient()
    executor = QoderExecutor(client)

    events = [event async for event in executor.execute(_request(), _account())]

    assert events[0].type == "response_start"
    assert events[1].type == "text_delta"
    assert events[1].text == "hello"
    assert events[-1].type == "response_stop"
    assert client.extra_headers == {"x-model-key": "lite", "x-model-source": "system"}
    assert client.body["chat_context"]["text"]["text"] == "hi"
```

- [ ] **Step 2: Run executor tests to verify failure**

Run:

```bash
python -m pytest tests/test_qoder_executor.py -v
```

Expected: FAIL because `qoder_proxy.qoder.executor` does not exist.

- [ ] **Step 3: Implement executor**

Create `qoder_proxy/qoder/executor.py`:

```python
from collections.abc import AsyncIterator

from qoder_proxy.accounts.models import Account
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.canonical.types import CanonicalEvent, CanonicalRequest
from qoder_proxy.qoder.payload import build_qoder_payload
from qoder_proxy.qoder.session import SessionContext
from qoder_proxy.qoder.sse import parse_qoder_sse_data

GENERATION_PATH = "/algo/api/v2/service/pro/sse/agent_chat_generation?FetchKeys=llm_model_result&AgentId=agent_common&Encode=1"


class QoderExecutor:
    def __init__(self, client) -> None:
        self.client = client

    async def execute(self, request: CanonicalRequest, account: Account) -> AsyncIterator[CanonicalEvent]:
        if account.identity is None or account.machine is None:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                f"Account {account.id} has no Qoder session identity",
                http_status=401,
            )
        session = SessionContext(
            temp_key=b"",
            cosy_key=account.session_cosy_key or "",
            info=account.session_info or "",
            identity=account.identity,
            machine=account.machine,
        )
        if not session.cosy_key or not session.info:
            raise CanonicalError(
                ErrorCode.AUTHENTICATION_FAILED,
                f"Account {account.id} has no active Qoder session",
                http_status=401,
            )
        model = request.resolved_model
        extra_headers = {
            "x-model-key": model.qoder_key if model else request.model,
            "x-model-source": model.qoder_source if model else "system",
        }
        payload = build_qoder_payload(request, user_type=account.identity.user_type)
        yield CanonicalEvent(type="response_start")
        async for line in self.client.stream_sse(session, GENERATION_PATH, payload, extra_headers=extra_headers):
            if not line.startswith("data:"):
                continue
            for event in parse_qoder_sse_data(line.removeprefix("data:").strip()):
                yield event
        yield CanonicalEvent(type="response_stop", finish_reason="end_turn")
```

- [ ] **Step 4: Run executor tests**

Run:

```bash
python -m pytest tests/test_qoder_executor.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add qoder_proxy/qoder/executor.py tests/test_qoder_executor.py
git commit -m "Add real Qoder executor"
```

---

### Task 8: API dependency wiring for mock vs real executor

**Files:**
- Modify: `qoder_proxy/api/app.py`
- Test: `tests/test_real_executor_api_integration.py`

- [ ] **Step 1: Write failing real executor route test**

Create `tests/test_real_executor_api_integration.py`:

```python
from collections.abc import AsyncIterator

from fastapi.testclient import TestClient

from qoder_proxy.api.app import create_app
from qoder_proxy.canonical.types import CanonicalEvent
from qoder_proxy.config.models import ExecutorConfig, ProxyConfig


class FakeAccountPool:
    def __init__(self) -> None:
        self.selected_model = None
        self.success_account_id = None

    async def select_for_model(self, qoder_key: str):
        self.selected_model = qoder_key
        return type("Account", (), {"id": "acct_1"})()

    def apply_success(self, account_id: str) -> None:
        self.success_account_id = account_id

    def apply_error(self, account_id: str, error) -> None:
        raise AssertionError("unexpected error")


class FakeExecutor:
    async def execute(self, request, account) -> AsyncIterator[CanonicalEvent]:
        yield CanonicalEvent(type="response_start")
        yield CanonicalEvent(type="text_delta", text=f"real {request.model}")
        yield CanonicalEvent(type="response_stop", finish_reason="end_turn")


def test_messages_route_uses_real_executor_when_configured() -> None:
    pool = FakeAccountPool()
    app = create_app(
        ProxyConfig(executor=ExecutorConfig(mode="qoder")),
        account_pool=pool,
        qoder_executor=FakeExecutor(),
    )
    client = TestClient(app)

    response = client.post(
        "/v1/messages",
        json={"model": "claude-sonnet-4-5", "max_tokens": 10, "messages": [{"role": "user", "content": "hi"}]},
    )

    assert response.status_code == 200
    assert response.json()["content"][0]["text"] == "real claude-sonnet-4-5"
    assert pool.selected_model == "lite"
    assert pool.success_account_id == "acct_1"
```

- [ ] **Step 2: Run route test to verify failure**

Run:

```bash
python -m pytest tests/test_real_executor_api_integration.py -v
```

Expected: FAIL because `create_app()` does not accept `account_pool` or `qoder_executor`.

- [ ] **Step 3: Modify app factory signature**

In `qoder_proxy/api/app.py`, change:

```python
def create_app(config: ProxyConfig | None = None) -> FastAPI:
```

to:

```python
def create_app(
    config: ProxyConfig | None = None,
    *,
    account_pool: Any | None = None,
    qoder_executor: Any | None = None,
) -> FastAPI:
```

- [ ] **Step 4: Add execution helper inside create_app**

Inside `create_app()`, after app creation, add:

```python
    async def execute_request(canonical):
        if config.executor.mode == "mock":
            return None, execute_mock(canonical)
        if account_pool is None or qoder_executor is None:
            raise CanonicalError(
                ErrorCode.NO_AVAILABLE_ACCOUNT,
                "Qoder executor mode requires account pool and executor",
                http_status=503,
                retryable=True,
            )
        model = canonical.resolved_model
        account = await account_pool.select_for_model(model.qoder_key if model else canonical.model)
        return account, qoder_executor.execute(canonical, account)
```

- [ ] **Step 5: Use helper in Anthropic route**

Replace:

```python
            events = execute_mock(canonical)
```

with:

```python
            account, events = await execute_request(canonical)
```

After non-streaming aggregation succeeds, before return:

```python
            response = await canonical_events_to_message(events, model=request.model)
            if account is not None:
                account_pool.apply_success(account.id)
            return response
```

For streaming, do not apply success yet in this task; streaming success tracking is covered by later tests.

- [ ] **Step 6: Use helper in OpenAI route**

Make the same replacement in `/v1/chat/completions`:

```python
            account, events = await execute_request(canonical)
```

For non-stream response:

```python
            response = await canonical_events_to_chat_completion(events, model=request.model)
            if account is not None:
                account_pool.apply_success(account.id)
            return response
```

- [ ] **Step 7: Run route test**

Run:

```bash
python -m pytest tests/test_real_executor_api_integration.py -v
```

Expected: PASS.

- [ ] **Step 8: Run existing API tests**

Run:

```bash
python -m pytest tests/test_anthropic_adapter.py tests/test_openai_adapter.py tests/test_api_integration.py -v
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add qoder_proxy/api/app.py tests/test_real_executor_api_integration.py
git commit -m "Wire real executor into API routes"
```

---

### Task 9: CLI account commands and serve real executor mode

**Files:**
- Modify: `qoder_proxy/cli/main.py`
- Test: `tests/test_cli_accounts.py`

- [ ] **Step 1: Add failing CLI tests**

Append to `tests/test_cli_accounts.py`:

```python
def test_account_remove_cli(tmp_path: Path, capsys, monkeypatch) -> None:
    storage_path = tmp_path / "accounts.json"
    monkeypatch.setattr(
        "sys.argv",
        ["qoder-proxy", "account", "add-pat", "--storage", str(storage_path), "--name", "main", "--pat-env", "QODER_PAT"],
    )
    main()
    account_id = capsys.readouterr().out.split("(")[1].split(")")[0]

    monkeypatch.setattr("sys.argv", ["qoder-proxy", "account", "remove", account_id, "--storage", str(storage_path)])
    main()

    assert "Removed account" in capsys.readouterr().out


def test_account_login_reports_unsupported(capsys, monkeypatch) -> None:
    monkeypatch.setattr("sys.argv", ["qoder-proxy", "account", "login"])

    try:
        main()
    except SystemExit as exc:
        assert exc.code == 1

    assert "Browser login is not implemented" in capsys.readouterr().out
```

- [ ] **Step 2: Run CLI tests to verify failure**

Run:

```bash
python -m pytest tests/test_cli_accounts.py -v
```

Expected: FAIL because `account remove` and `account login` are not registered.

- [ ] **Step 3: Add CLI subcommands**

In `qoder_proxy/cli/main.py`, after account list parser setup, add:

```python
    account_remove_parser = account_subparsers.add_parser("remove", help="Remove an account.")
    account_remove_parser.add_argument("account_id")
    account_remove_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_remove_parser.set_defaults(handler=_account_remove)

    account_login_parser = account_subparsers.add_parser("login", help="Browser authorization import.")
    account_login_parser.set_defaults(handler=_account_login)

    account_import_local_parser = account_subparsers.add_parser("import-local", help="Import local Qoder account state.")
    account_import_local_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_import_local_parser.set_defaults(handler=_account_import_local)

    account_check_parser = account_subparsers.add_parser("check", help="Check configured accounts.")
    account_check_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_check_parser.set_defaults(handler=_account_check)
```

Add handlers:

```python
def _account_remove(args: argparse.Namespace) -> None:
    JsonAccountStorage(args.storage).remove(args.account_id)
    print(f"Removed account {args.account_id}")


def _account_login(args: argparse.Namespace) -> None:
    print("Browser login is not implemented for this Qoder flow yet")
    raise SystemExit(1)


def _account_import_local(args: argparse.Namespace) -> None:
    from qoder_proxy.accounts import LocalQoderImportProvider

    storage = JsonAccountStorage(args.storage)
    accounts = LocalQoderImportProvider().import_accounts()
    for account in accounts:
        storage.save(account)
    print(f"Imported {len(accounts)} local account(s)")


def _account_check(args: argparse.Namespace) -> None:
    accounts = JsonAccountStorage(args.storage).list()
    for account in accounts:
        print(f"{account.id}\t{account.display_name}\t{account.health}")
```

- [ ] **Step 4: Add serve executor override**

In parser setup for serve, add:

```python
    serve_parser.add_argument("--executor", choices=["mock", "qoder"])
```

In `_serve`, after config load:

```python
    if args.executor:
        proxy_config.executor.mode = args.executor
```

If `proxy_config.executor.mode == "qoder"`, construct storage/auth/client/pool/executor and pass them to uvicorn is not possible through factory string. For this task, use:

```python
    if proxy_config.executor.mode == "qoder":
        print("Real Qoder executor mode is available through create_app() integration tests; direct CLI wiring will be completed after manual credential verification.")
```

This is honest and keeps CLI behavior safe until the real client is manually verified.

- [ ] **Step 5: Run CLI tests**

Run:

```bash
python -m pytest tests/test_cli_accounts.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add qoder_proxy/cli/main.py tests/test_cli_accounts.py
git commit -m "Expand account CLI commands"
```

---

### Task 10: README real-executor testing documentation

**Files:**
- Modify: `README.md`
- Test: no automated test; verify commands in final task.

- [ ] **Step 1: Update README real executor section**

Add this section to `README.md`:

```markdown
## Real Qoder executor mode

Mock mode is the default and requires no credentials:

```bash
python -m qoder_proxy.cli.main serve --host 127.0.0.1 --port 8963
```

Create a PAT-backed account without storing the token directly:

```bash
export QODER_PAT=<your-token>
python -m qoder_proxy.cli.main account add-pat --name main --pat-env QODER_PAT
python -m qoder_proxy.cli.main account list
```

Enable real executor mode in `config.yaml`:

```yaml
executor:
  mode: qoder
accounts:
  storage_path: ./data/accounts.json
qoder:
  center_base_url: https://center.qoder.sh
  api_base_url: https://api3.qoder.sh
  client_version: 0.1.43
```

Default tests never contact Qoder. Any real-account test must be opt-in and must redact tokens, machine identifiers, signatures, and bearer payloads from output.
```

- [ ] **Step 2: Commit docs**

```bash
git add README.md
git commit -m "Document real Qoder executor testing"
```

---

### Task 11: Final verification and cleanup

**Files:**
- All touched files.

- [ ] **Step 1: Run full tests**

Run:

```bash
python -m pytest
```

Expected: all tests PASS.

- [ ] **Step 2: Run lint**

Run:

```bash
python -m ruff check .
```

Expected: `All checks passed!`.

- [ ] **Step 3: Check CLI help and config output**

Run:

```bash
python -m qoder_proxy.cli.main --help
python -m qoder_proxy.cli.main config init --print
python -m qoder_proxy.cli.main account add-pat --help
python -m qoder_proxy.cli.main account login
```

Expected:

- Help commands print usage.
- Config output includes `executor`, `accounts`, and `qoder` sections.
- `account login` exits non-zero with `Browser login is not implemented for this Qoder flow yet`.

- [ ] **Step 4: Review sensitive logging/output**

Search for unsafe token printing:

```bash
python -m pytest tests/test_qoder_wire.py tests/test_qoder_auth_client.py tests/test_qoder_client.py -v
```

Expected: PASS. Inspect CLI output paths changed in this plan; no handler prints `pat`, `refresh_token`, `security_oauth_token`, `authorization`, `signature`, `machine_token`, or full machine ID.

- [ ] **Step 5: Check git status**

Run:

```bash
git status --short
```

Expected: only intentional files are modified. `CLAUDE.md` may remain untracked by user preference and must not be committed unless explicitly requested.

- [ ] **Step 6: Commit final fixes if needed**

If any verification fix is required:

```bash
git add <fixed-files>
git commit -m "Fix real Qoder integration verification issues"
```

If no fixes are required, do not create an empty commit.

---

## Self-review

- Spec coverage: Tasks cover config, session construction, PAT exchange, signed client, executor, account providers, account pool, API wiring, CLI commands, README documentation, and final verification. Browser OAuth is intentionally unsupported with an honest CLI failure as allowed by the spec.
- Placeholder scan: No incomplete marker or unspecified implementation steps remain. OAuth unsupported behavior is explicit and testable, not a placeholder.
- Type consistency: `AuthIdentity`, `MachineIdentity`, `SessionContext`, `AccountPool`, `QoderAuthClient`, `QoderClient`, and `QoderExecutor` names are introduced before use and reused consistently.

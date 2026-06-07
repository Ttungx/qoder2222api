import json
import time
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from qoder_proxy.accounts import (
    Account,
    AccountHealth,
    AccountPool,
    JsonAccountStorage,
    LocalQoderImportProvider,
)
from qoder_proxy.adapters.anthropic import (
    AnthropicMessageRequest,
    canonical_events_to_message,
    canonical_events_to_sse,
)
from qoder_proxy.adapters.anthropic import request_to_canonical as anthropic_to_canonical
from qoder_proxy.adapters.openai import (
    OpenAIChatRequest,
    canonical_events_to_chat_completion,
    canonical_events_to_chat_sse,
)
from qoder_proxy.adapters.openai import request_to_canonical as openai_to_canonical
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.config import (
    ModelAliasConfig,
    ModelResolver,
    ProxyConfig,
    load_config,
    model_to_openai,
)
from qoder_proxy.qoder.mock import execute_mock

# ── Simple in-memory stats tracker ──────────────────────────────────────────
_stats: dict[str, Any] = {
    "started_at": 0,
    "total_requests": 0,
    "total_success": 0,
    "total_error": 0,
    "requests_by_model": {},
}


def create_app(
    config: ProxyConfig | None = None,
    *,
    account_pool: Any | None = None,
    qoder_executor: Any | None = None,
) -> FastAPI:
    config = config or load_config()
    resolver = ModelResolver(config.models)
    app = FastAPI(title="Qoder Proxy", version="0.1.0")
    _stats["started_at"] = time.time()

    # Auto-initialize account pool if not provided
    from pathlib import Path
    if account_pool is None:
        storage_path = Path(config.accounts.storage_path)
        account_pool = AccountPool(storage=JsonAccountStorage(storage_path))

    # Auto-initialize executor and PAT provider when in qoder mode
    if qoder_executor is None and config.executor.mode == "qoder":
        from qoder_proxy.accounts.providers import PATAccountProvider
        from qoder_proxy.qoder.auth import QoderAuthClient
        from qoder_proxy.qoder.client import QoderClient
        from qoder_proxy.qoder.executor import QoderExecutor

        auth_client = QoderAuthClient(center_base_url=config.qoder.center_base_url)
        pat_provider = PATAccountProvider(auth_client)
        account_pool.pat_provider = pat_provider
        qoder_client = QoderClient(api_base_url=config.qoder.api_base_url)
        qoder_executor = QoderExecutor(qoder_client)  # executor takes client directly
        print("[qoder-proxy] Qoder executor initialized (real mode)")
    elif qoder_executor is None:
        print("[qoder-proxy] Running in mock executor mode")

    # Model storage (runtime models stored in data/models.json)
    _models_path = Path(config.accounts.storage_path).parent / "models.json"

    def _load_runtime_models() -> list[ModelAliasConfig]:
        if not _models_path.exists():
            return []
        try:
            data = json.loads(_models_path.read_text(encoding="utf-8"))
            return [ModelAliasConfig(**m) for m in data.get("models", [])]
        except (json.JSONDecodeError, ValidationError):
            return []

    def _save_runtime_models(models: list[ModelAliasConfig]) -> None:
        _models_path.parent.mkdir(parents=True, exist_ok=True)
        data = {"models": [m.model_dump() for m in models]}
        _models_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _all_models() -> list[ModelAliasConfig]:
        runtime = _load_runtime_models()
        cfg_aliases = {m.alias for m in config.models}
        merged = list(config.models)
        for m in runtime:
            if m.alias not in cfg_aliases:
                merged.append(m)
        return merged

    def _rebuild_resolver() -> None:
        nonlocal resolver
        resolver = ModelResolver(_all_models())

    # ── Dashboard API ───────────────────────────────────────────────────────

    @app.get("/api/dashboard")
    async def dashboard() -> dict[str, Any]:
        accounts: list[dict[str, Any]] = []
        if account_pool is not None:
            for a in account_pool.storage.list():
                accounts.append({
                    "id": a.id,
                    "display_name": a.display_name,
                    "source": a.source,
                    "enabled": a.enabled,
                    "health": a.health,
                    "failure_count": a.failure_count,
                    "supported_models": a.supported_models,
                    "cooldown_until": a.cooldown_until.isoformat() if a.cooldown_until else None,
                })
        uptime = int(time.time() - _stats["started_at"]) if _stats["started_at"] else 0
        return {
            "server": {
                "host": config.server.host,
                "port": config.server.port,
                "executor_mode": config.executor.mode,
                "uptime_seconds": uptime,
                "api_keys_count": len(config.server.api_keys),
            },
            "accounts": accounts,
            "models": [
                {
                    "id": m.alias,
                    "object": "model",
                    "owned_by": "qoder",
                    "qoder_key": m.qoder_key,
                    "qoder_source": m.qoder_source,
                    "is_config": m.alias in {c.alias for c in config.models},
                }
                for m in _all_models()
            ],
            "stats": {
                "total_requests": _stats["total_requests"],
                "total_success": _stats["total_success"],
                "total_error": _stats["total_error"],
                "requests_by_model": _stats["requests_by_model"],
            },
        }

    # ── Account Management API ──────────────────────────────────────────────

    def _get_pool() -> AccountPool | None:
        return account_pool

    @app.get("/api/accounts")
    async def api_list_accounts() -> dict[str, Any]:
        pool = _get_pool()
        if pool is None:
            return {"accounts": []}
        return {"accounts": [_account_to_dict(a) for a in pool.storage.list()]}

    @app.post("/api/accounts")
    async def api_add_account(payload: dict[str, Any]) -> dict[str, Any]:
        pool = _get_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Account pool not initialized")
        from uuid import uuid4
        name = payload.get("display_name", "").strip()
        pat = payload.get("pat")
        pat_env = payload.get("pat_env")
        if not name:
            raise HTTPException(status_code=400, detail="display_name is required")
        if not pat and not pat_env:
            raise HTTPException(status_code=400, detail="pat or pat_env is required")
        account = Account(
            id=f"acct_{uuid4().hex[:12]}",
            display_name=name,
            source="pat",
            pat=pat,
            pat_env=pat_env,
        )
        pool.storage.save(account)
        return {"ok": True, "account": _account_to_dict(account)}

    @app.delete("/api/accounts/{account_id}")
    async def api_remove_account(account_id: str) -> dict[str, Any]:
        pool = _get_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Account pool not initialized")
        try:
            pool.storage.remove(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Account not found: {account_id}",
            ) from None
        return {"ok": True, "removed": account_id}

    @app.patch("/api/accounts/{account_id}")
    async def api_update_account(account_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        pool = _get_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Account pool not initialized")
        try:
            account = pool.storage.get(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"Account not found: {account_id}",
            ) from None
        updates: dict[str, Any] = {}
        if "enabled" in payload:
            updates["enabled"] = bool(payload["enabled"])
        if "reset_health" in payload and payload["reset_health"]:
            updates.update({"health": AccountHealth.OK, "failure_count": 0, "cooldown_until": None})
        account = account.model_copy(update=updates)
        pool.storage.save(account)
        return {"ok": True, "account": _account_to_dict(account)}

    @app.post("/api/accounts/import-local")
    async def api_import_local() -> dict[str, Any]:
        pool = _get_pool()
        if pool is None:
            raise HTTPException(status_code=503, detail="Account pool not initialized")
        imported = LocalQoderImportProvider().import_accounts()
        for account in imported:
            pool.storage.save(account)
        return {
            "ok": True,
            "imported": len(imported),
            "accounts": [_account_to_dict(a) for a in imported],
        }

    def _account_to_dict(a: Account) -> dict[str, Any]:
        return {
            "id": a.id,
            "display_name": a.display_name,
            "source": a.source,
            "enabled": a.enabled,
            "health": a.health,
            "failure_count": a.failure_count,
            "supported_models": a.supported_models,
            "cooldown_until": a.cooldown_until.isoformat() if a.cooldown_until else None,
        }

    # ── Model Alias Management API ─────────────────────────────────────────

    @app.get("/api/models")
    async def api_list_models() -> dict[str, Any]:
        models = _all_models()
        return {
            "models": [
                {"alias": m.alias, "qoder_key": m.qoder_key, "qoder_source": m.qoder_source}
                for m in models
            ],
        }

    @app.post("/api/models")
    async def api_add_model(payload: dict[str, Any]) -> dict[str, Any]:
        alias = payload.get("alias", "").strip()
        qoder_key = payload.get("qoder_key", "").strip()
        qoder_source = payload.get("qoder_source", "system").strip()
        if not alias or not qoder_key:
            raise HTTPException(status_code=400, detail="alias and qoder_key are required")
        new_model = ModelAliasConfig(alias=alias, qoder_key=qoder_key, qoder_source=qoder_source)
        runtime = _load_runtime_models()
        # Check for duplicates
        all_aliases = {m.alias for m in config.models} | {m.alias for m in runtime}
        if alias in all_aliases:
            raise HTTPException(status_code=409, detail=f"Model alias already exists: {alias}")
        runtime.append(new_model)
        _save_runtime_models(runtime)
        _rebuild_resolver()
        return {"ok": True, "model": new_model.model_dump()}

    @app.delete("/api/models/{alias}")
    async def api_remove_model(alias: str) -> dict[str, Any]:
        # Cannot remove config-level models via API
        config_aliases = {m.alias for m in config.models}
        if alias in config_aliases:
            raise HTTPException(
                status_code=400, detail=f"Cannot remove config-level model: {alias}",
            )
        runtime = _load_runtime_models()
        before = len(runtime)
        runtime = [m for m in runtime if m.alias != alias]
        if len(runtime) == before:
            raise HTTPException(
                status_code=404, detail=f"Model alias not found: {alias}",
            ) from None
        _save_runtime_models(runtime)
        _rebuild_resolver()
        return {"ok": True, "removed": alias}

    # ── OAuth Browser Login API ────────────────────────────────────────────

    import base64
    import hashlib
    import secrets
    from uuid import uuid4

    import httpx

    _OAUTH_CLIENT_ID = "e883ade2-e6e3-4d6d-adf7-f92ceff5fdcb"
    _OPENAPI_BASE = "https://openapi.qoder.sh"
    _oauth_sessions: dict[str, dict[str, Any]] = {}

    @app.post("/api/oauth/start")
    async def api_oauth_start() -> dict[str, Any]:
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
        code_challenge = (
            base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
            .rstrip(b"=").decode()
        )
        nonce = uuid4().hex
        login_id = uuid4().hex[:16]
        machine_token = secrets.token_urlsafe(50)

        verification_uri = (
            f"https://qoder.com/device/selectAccounts"
            f"?nonce={nonce}"
            f"&challenge={code_challenge}"
            f"&challenge_method=S256"
            f"&client_id={_OAUTH_CLIENT_ID}"
            f"&machine_id={machine_token}"
        )

        _oauth_sessions[login_id] = {
            "nonce": nonce,
            "code_verifier": code_verifier,
            "machine_token": machine_token,
            "verification_uri": verification_uri,
            "created_at": time.time(),
            "status": "pending",
            "account": None,
        }
        print(f"[qoder-proxy] OAuth login started: login_id={login_id}")
        print(f"[qoder-proxy] Verification URI: {verification_uri[:80]}...")

        return {
            "login_id": login_id,
            "verification_uri": verification_uri,
            "expires_in": 600,
            "interval": 2,
        }

    @app.post("/api/oauth/poll/{login_id}")
    async def api_oauth_poll(login_id: str) -> dict[str, Any]:
        session = _oauth_sessions.get(login_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Login session not found")
        if session["status"] == "completed":
            return {"status": "completed", "account": session["account"]}
        if time.time() - session["created_at"] > 600:
            return {"status": "expired"}

        # Poll Qoder openapi device token endpoint
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                resp = await client.get(
                    f"{_OPENAPI_BASE}/api/v1/deviceToken/poll",
                    params={
                        "nonce": session["nonce"],
                        "verifier": session["code_verifier"],
                        "challenge_method": "S256",
                    },
                )
                # 404 = user hasn't authorized yet, keep polling
                if resp.status_code == 404:
                    return {"status": "pending"}

                if resp.status_code == 200:
                    token_data = resp.json()
                    # Key fix: field name is "token", not "access_token"
                    access_token = (
                        token_data.get("token")
                        or token_data.get("access_token")
                        or ""
                    )
                    if not access_token:
                        # 200 but no token yet = still pending
                        return {"status": "pending"}

                    refresh_token = token_data.get("refresh_token", "")
                    user_id = token_data.get("user_id", "")

                    # Fetch user info
                    user_info = await _fetch_oauth_user_info(client, access_token)
                    # Merge user_id from poll response if userinfo didn't return one
                    if not user_info.get("id") and user_id:
                        user_info["id"] = user_id
                    identity = _build_oauth_identity(user_info, access_token, refresh_token)
                    machine = _new_machine()

                    # Build session immediately so session_info / session_cosy_key
                    # are populated and persisted for the executor.
                    from qoder_proxy.qoder.session import SessionBuilder
                    qoder_session = SessionBuilder.new_session(identity, machine)

                    # Create account
                    acct = Account(
                        id=f"acct_{uuid4().hex[:12]}",
                        display_name=identity.name or identity.uid or user_id,
                        source="oauth",
                        identity=identity,
                        machine=machine,
                        session_info=qoder_session.info,
                        session_cosy_key=qoder_session.cosy_key,
                    )
                    pool = _get_pool()
                    if pool is not None:
                        pool.storage.save(acct)
                    session["status"] = "completed"
                    session["account"] = _account_to_dict(acct)
                    print(f"[qoder-proxy] OAuth login completed: {acct.display_name}")
                    return {"status": "completed", "account": session["account"]}

                # Other status codes = transient error, keep polling
                print(f"[qoder-proxy] OAuth poll unexpected status: {resp.status_code}")
                return {"status": "pending"}
        except Exception as exc:
            print(f"[qoder-proxy] OAuth poll error: {exc}")
            return {"status": "pending"}

    async def _fetch_oauth_user_info(client: httpx.AsyncClient, token: str) -> dict[str, Any]:
        resp = await client.get(
            f"{_OPENAPI_BASE}/api/v1/userinfo",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 200:
            return resp.json()
        return {}

    def _build_oauth_identity(
        info: dict[str, Any], access_token: str, refresh_token: str,
    ) -> Any:
        from qoder_proxy.qoder.session import AuthIdentity
        return AuthIdentity(
            name=str(info.get("name", "")),
            aid=str(info.get("id", "")),
            uid=str(info.get("id", "")),
            user_type=str(info.get("userType", "personal_standard")),
            security_oauth_token=access_token,
            refresh_token=refresh_token,
        )

    def _new_machine() -> Any:
        from qoder_proxy.qoder.session import MachineIdentity
        return MachineIdentity(
            machine_id=str(uuid4()),
            machine_token=secrets.token_urlsafe(50),
            machine_type=uuid4().hex[:18],
        )

    # ── Proxy API ───────────────────────────────────────────────────────────

    async def execute_request(canonical: Any) -> tuple[Any | None, AsyncIterator[Any]]:
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

    @app.middleware("http")
    async def api_key_middleware(request: Request, call_next: Any) -> Any:
        path = request.url.path
        exempt = ("/health", "/", "/static")
        is_static = path.startswith("/static/") or path.startswith("/api/")
        if config.server.api_keys and path not in exempt and not is_static:
            auth = request.headers.get("authorization", "")
            token = auth.removeprefix("Bearer ").strip()
            if token not in config.server.api_keys:
                error = CanonicalError(
                    ErrorCode.AUTHENTICATION_FAILED,
                    "Missing or invalid API key",
                    http_status=401,
                )
                return JSONResponse(status_code=401, content=_anthropic_error_payload(error))
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        return {
            "object": "list",
            "data": [model_to_openai(model) for model in resolver.list_models()],
        }

    @app.post("/v1/messages")
    async def create_message(payload: dict[str, Any]) -> Any:
        _stats["total_requests"] += 1
        try:
            request = AnthropicMessageRequest.model_validate(payload)
            model = resolver.resolve(request.model)
            canonical = anthropic_to_canonical(request, model)
            account, events = await execute_request(canonical)
            if request.stream:
                return StreamingResponse(
                    _stream_with_errors(
                        canonical_events_to_sse(events, model=request.model),
                        account=account,
                        account_pool=account_pool,
                    ),
                    media_type="text/event-stream",
                )
            response = await canonical_events_to_message(events, model=request.model)
            if account is not None:
                account_pool.apply_success(account.id)
            _track_success(request.model)
            return response
        except ValidationError as exc:
            _track_error(payload.get("model", "unknown"))
            raise _http_error(
                CanonicalError(ErrorCode.INVALID_REQUEST, exc.errors()[0]["msg"], http_status=400)
            ) from exc
        except CanonicalError as exc:
            _track_error(payload.get("model", "unknown"))
            raise _http_error(exc) from exc

    @app.post("/v1/chat/completions")
    async def create_chat_completion(payload: dict[str, Any]) -> Any:
        _stats["total_requests"] += 1
        try:
            request = OpenAIChatRequest.model_validate(payload)
            model = resolver.resolve(request.model)
            canonical = openai_to_canonical(request, model)
            account, events = await execute_request(canonical)
            if request.stream:
                return StreamingResponse(
                    _stream_with_errors(
                        canonical_events_to_chat_sse(events, model=request.model),
                        account=account,
                        account_pool=account_pool,
                    ),
                    media_type="text/event-stream",
                )
            response = await canonical_events_to_chat_completion(events, model=request.model)
            if account is not None:
                account_pool.apply_success(account.id)
            _track_success(request.model)
            return response
        except ValidationError as exc:
            _track_error(payload.get("model", "unknown"))
            raise _openai_http_error(
                CanonicalError(ErrorCode.INVALID_REQUEST, exc.errors()[0]["msg"], http_status=400)
            ) from exc
        except CanonicalError as exc:
            _track_error(payload.get("model", "unknown"))
            raise _openai_http_error(exc) from exc

    # ── Track success/error in stats ───────────────────────────────────────

    def _track_success(model: str) -> None:
        _stats["total_success"] += 1
        _stats["requests_by_model"][model] = _stats["requests_by_model"].get(model, 0) + 1

    def _track_error(model: str) -> None:
        _stats["total_error"] += 1

    # ── Mount static frontend ──────────────────────────────────────────────

    import pathlib as _pathlib

    _web_dir = _pathlib.Path(__file__).resolve().parent.parent / "web"
    if _web_dir.is_dir():
        from fastapi.responses import FileResponse

        @app.get("/")
        async def serve_frontend() -> FileResponse:
            return FileResponse(_web_dir / "index.html")

        app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")

    return app


async def _stream_with_errors(
    source: AsyncIterator[str],
    *,
    account: Any | None = None,
    account_pool: Any | None = None,
) -> AsyncIterator[str]:
    try:
        async for item in source:
            yield item
    except CanonicalError as exc:
        if account is not None and account_pool is not None:
            account_pool.apply_error(account.id, exc)
        error_payload = {
            "type": "error",
            "error": {"type": str(exc.code), "message": exc.message},
        }
        yield f"event: error\ndata: {json.dumps(error_payload)}\n\n"
    else:
        if account is not None and account_pool is not None:
            account_pool.apply_success(account.id)


def _anthropic_error_payload(error: CanonicalError) -> dict[str, Any]:
    return {"detail": {"type": "error", "error": {"type": error.code, "message": error.message}}}


def _http_error(error: CanonicalError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"type": "error", "error": {"type": error.code, "message": error.message}},
    )


def _openai_http_error(error: CanonicalError) -> HTTPException:
    return HTTPException(
        status_code=error.http_status,
        detail={"error": {"type": error.code, "message": error.message}},
    )

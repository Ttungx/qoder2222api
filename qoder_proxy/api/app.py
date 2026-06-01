import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

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
from qoder_proxy.config import ModelResolver, ProxyConfig, load_config, model_to_openai
from qoder_proxy.qoder.mock import execute_mock


def create_app(
    config: ProxyConfig | None = None,
    *,
    account_pool: Any | None = None,
    qoder_executor: Any | None = None,
) -> FastAPI:
    config = config or load_config()
    resolver = ModelResolver(config.models)
    app = FastAPI(title="Qoder Proxy", version="0.1.0")

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
        if config.server.api_keys and request.url.path != "/health":
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
            return response
        except ValidationError as exc:
            raise _http_error(
                CanonicalError(ErrorCode.INVALID_REQUEST, exc.errors()[0]["msg"], http_status=400)
            ) from exc
        except CanonicalError as exc:
            raise _http_error(exc) from exc

    @app.post("/v1/chat/completions")
    async def create_chat_completion(payload: dict[str, Any]) -> Any:
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
            return response
        except ValidationError as exc:
            raise _openai_http_error(
                CanonicalError(ErrorCode.INVALID_REQUEST, exc.errors()[0]["msg"], http_status=400)
            ) from exc
        except CanonicalError as exc:
            raise _openai_http_error(exc) from exc

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

# Qoder Python Proxy Implementation Plan

## Source design

Spec: `docs/superpowers/specs/2026-06-01-qoder-python-proxy-design.md`

This plan turns the approved design into implementation phases for a lightweight Python proxy that exposes Qoder through Anthropic `/v1/messages` and OpenAI `/v1/chat/completions`, with Claude Code compatibility as the priority.

## Phase 1: Project scaffold and developer workflow

Goal: create a clean Python project skeleton with repeatable local commands.

Tasks:

1. Create `pyproject.toml` for Python 3.11+.
2. Add runtime dependencies:
   - `fastapi`
   - `uvicorn[standard]`
   - `httpx`
   - `pydantic`
   - `pyyaml`
   - `typer`
   - `aiosqlite` or standard-library JSON storage if SQLite is deferred
3. Add dev dependencies:
   - `pytest`
   - `pytest-asyncio`
   - `ruff`
   - `mypy` if strict typing remains practical
4. Create package layout:
   - `qoder_proxy/api/`
   - `qoder_proxy/adapters/`
   - `qoder_proxy/canonical/`
   - `qoder_proxy/qoder/`
   - `qoder_proxy/accounts/`
   - `qoder_proxy/config/`
   - `qoder_proxy/cli/`
   - `tests/`
5. Add CLI entrypoint `qoder-proxy`.
6. Add minimal `README.md` with local run commands.
7. Update `CLAUDE.md` with Python project commands after scaffold exists.

Validation:

```bash
python -m pytest
python -m ruff check .
qoder-proxy --help
```

## Phase 2: Canonical data model and errors

Goal: establish the shared internal representation before adding API routes.

Tasks:

1. Define canonical request/event/error types.
2. Model message roles, content blocks, tool calls, tool results, model options, and stream mode.
3. Define stable error codes:
   - `invalid_request`
   - `unsupported_feature`
   - `unknown_model`
   - `no_available_account`
   - `authentication_failed`
   - `rate_limited`
   - `quota_exhausted`
   - `upstream_error`
   - `stream_interrupted`
   - `internal_error`
4. Add protocol-neutral helpers for tool-call accumulation.
5. Unit test canonical model serialization and tool-call merging.

Validation:

```bash
python -m pytest tests/test_canonical.py
```

## Phase 3: Configuration and model alias resolution

Goal: load local config and resolve client-visible model names to Qoder model metadata.

Tasks:

1. Implement `config.yaml` loader with environment overrides.
2. Define config schema for:
   - server host/port
   - storage path
   - logging level
   - model aliases
   - PAT account list or env account references
   - reserved server fields such as API keys and trusted proxies
3. Add default config generation command.
4. Implement model alias resolver.
5. Add `/v1/models` data model shared by both protocol surfaces.

Validation:

```bash
qoder-proxy config init --print
python -m pytest tests/test_config.py
```

## Phase 4: Anthropic adapter and `/v1/messages`

Goal: implement Claude Code-facing request parsing and response formatting without real Qoder yet.

Tasks:

1. Convert Anthropic message requests into `CanonicalRequest`.
2. Support fields: `model`, `system`, `messages`, `tools`, `tool_choice`, `max_tokens`, `stop_sequences`, `temperature`, `top_p`, `stream`.
3. Support content blocks: `text`, `tool_use`, `tool_result`.
4. Reject or explicitly placeholder unsupported image/file blocks.
5. Convert canonical events to Anthropic non-streaming responses.
6. Convert canonical events to Anthropic SSE events:
   - `message_start`
   - `content_block_start`
   - `content_block_delta`
   - `content_block_stop`
   - `message_delta`
   - `message_stop`
   - `error`
7. Add a mock executor so `/v1/messages` can be tested before Qoder integration.

Validation:

```bash
python -m pytest tests/test_anthropic_adapter.py
uvicorn qoder_proxy.api.app:create_app --factory --host 127.0.0.1 --port 8963
```

Manual check with curl against `/v1/messages` for stream and non-stream responses.

## Phase 5: OpenAI adapter and `/v1/chat/completions`

Goal: implement Codex/OpenAI-facing request parsing and response formatting through the same canonical model.

Tasks:

1. Convert OpenAI chat requests into `CanonicalRequest`.
2. Support roles: `system`, `user`, `assistant`, `tool`.
3. Support fields: `model`, `messages`, `tools`, `tool_choice`, `stream`, `temperature`, `top_p`, `max_tokens`, `stop`.
4. Support `tool_calls` and `tool_call_id`.
5. Convert canonical events to non-streaming chat completion responses.
6. Convert canonical events to OpenAI SSE chunks and `[DONE]`.
7. Reuse the mock executor for route tests.

Validation:

```bash
python -m pytest tests/test_openai_adapter.py
```

Manual check with curl against `/v1/chat/completions` for stream and non-stream responses.

## Phase 6: Qoder wire compatibility

Goal: port the known Qoder auth/signing/request/SSE behavior from the Java prototype.

Tasks:

1. Port Qoder encoding behavior from `qoder2api/src/main/java/us/cubk/QoderEncoding.java`.
2. Port signature behavior from `Signature.java`.
3. Port bearer/session behavior from `BearerBuilder.java`.
4. Implement PAT-to-session exchange based on `SignatureApiClient.exchangeJobToken`.
5. Implement signed Qoder POST and SSE streaming client based on `BearerApiClient`.
6. Create Qoder payload builder from `baseprompt.json` behavior.
7. Convert canonical messages and tools into Qoder payload messages.
8. Parse Qoder SSE events into canonical events.
9. Add redaction helpers for every sensitive value used by this layer.

Validation:

```bash
python -m pytest tests/test_qoder_encoding.py tests/test_qoder_sse.py
```

Manual check requires a real Qoder account token and should be opt-in through environment variables, not part of default tests.

## Phase 7: Account storage, import, health, and quota scheduler

Goal: make multi-account routing usable for local operation.

Tasks:

1. Implement storage interface and first backend.
2. Add `account add-pat` command.
3. Add account session refresh lifecycle.
4. Add account list/check/remove commands.
5. Implement scheduler filters:
   - enabled
   - health status
   - cooldown deadline
   - model support
6. Implement quota-aware score when quota data is available.
7. Implement fallback health-aware round robin when quota data is unavailable.
8. Classify upstream failures into account state changes:
   - auth failure disables or requires reauth
   - rate limit triggers short cooldown
   - quota exhaustion triggers quota cooldown
   - upstream 5xx triggers temporary penalty
   - network errors trigger retryable penalty
9. Add placeholders/interfaces for `account login` and `account import-local` if full OAuth/local import cannot be completed in this phase.

Validation:

```bash
python -m pytest tests/test_accounts.py tests/test_scheduler.py
qoder-proxy account add-pat --help
qoder-proxy account list
```

## Phase 8: End-to-end proxy integration

Goal: connect API routes, scheduler, and Qoder executor.

Tasks:

1. Wire FastAPI dependency graph:
   - config
   - storage
   - account pool
   - scheduler
   - executor
2. Implement request lifecycle:
   - parse client request
   - resolve model alias
   - select account
   - execute Qoder request
   - stream or aggregate response
   - update account health/quota state
3. Convert canonical errors to Anthropic/OpenAI errors.
4. Add graceful stream cancellation handling.
5. Add request logging with redaction.
6. Add startup validation for config, models, and account availability.

Validation:

```bash
python -m pytest tests/test_api_routes.py tests/test_integration_mock_qoder.py
qoder-proxy serve --config config.yaml
```

Manual local checks:

- Anthropic stream response works through `/v1/messages`.
- OpenAI stream response works through `/v1/chat/completions`.
- Tool call deltas round-trip in both protocols.
- Account cooldown/fallback works when mock upstream returns rate limit or quota exhaustion.

## Phase 9: Claude Code and Codex acceptance hardening

Goal: verify the project against the real target clients.

Tasks:

1. Document Claude Code environment/config needed to point at local Anthropic-compatible API.
2. Document Codex/OpenAI client base URL and model configuration.
3. Run Claude Code workflows:
   - simple prompt
   - streaming response
   - tool call
   - tool result continuation
   - model list or configured model alias
   - upstream error display
4. Run Codex/OpenAI workflows:
   - simple prompt
   - streaming response
   - tool call
   - non-stream response
5. Add fixes only for issues discovered in these target workflows.
6. Capture known limitations in README.

Validation:

Manual acceptance with real clients is required before considering the first version usable.

## Phase 10: Deployment foundation without full server mode

Goal: prepare for future server deployment without implementing full multi-tenant management.

Tasks:

1. Add optional API key middleware behind config.
2. Add Dockerfile only after local path is stable.
3. Add documented `host`/`port` config for non-local binding, defaulting to `127.0.0.1`.
4. Ensure storage path and logs work with mounted directories.
5. Keep team account isolation and advanced rate limiting out of scope.

Validation:

```bash
python -m pytest
qoder-proxy serve --host 127.0.0.1 --port 8963
```

## First implementation slice

Start with Phases 1-3, then add Anthropic mock route from Phase 4 before touching Qoder upstream behavior. This creates a stable shell where Claude Code compatibility can be tested against deterministic mock events before debugging Qoder signing and SSE details.

Recommended first milestone deliverable:

- Python package skeleton.
- `qoder-proxy` CLI.
- `config init` and model alias resolver.
- `/v1/models`.
- `/v1/messages` backed by mock canonical events.
- Unit tests for canonical types, config, and Anthropic adapter.

Do not implement Qoder wire calls until the canonical and Anthropic surfaces are tested.

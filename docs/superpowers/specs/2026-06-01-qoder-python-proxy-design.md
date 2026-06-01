# Qoder Python Proxy Design

## Goal

Build a lightweight Python reverse proxy that lets Claude Code and Codex/OpenAI-compatible clients use Qoder-backed models through familiar API formats. The first usable version prioritizes local personal use while laying clean boundaries for later server deployment.

Primary compatibility targets:

- Claude Code via Anthropic-compatible `/v1/messages`.
- Codex/OpenAI clients via OpenAI-compatible `/v1/chat/completions`.
- Multi-account Qoder routing with quota-aware scheduling.
- CLI and configuration-file management, without a web UI in the first version.

## Non-goals for the first version

- Public multi-tenant server mode.
- Web management UI.
- OpenAI Responses API.
- Deep image/file compatibility.
- Billing or detailed usage dashboard.
- Full reproduction of every Qoder client feature before the proxy path is stable.

## Architecture

The service is a FastAPI application with five layers:

1. **API layer** exposes OpenAI and Anthropic compatible endpoints, validates request shape, and returns protocol-specific response formats.
2. **Protocol adapter layer** converts OpenAI and Anthropic request/response objects into a canonical internal representation.
3. **Qoder execution layer** converts canonical requests into Qoder wire payloads, applies Qoder encoding/signing, calls upstream SSE endpoints, and emits canonical response events.
4. **Account pool layer** manages account import, sessions, health, quota data, cooldowns, and request scheduling.
5. **CLI/config layer** starts the service and manages accounts through commands and `config.yaml`.

Boundaries are intentionally strict: protocol adapters do not know account internals, the account pool does not know OpenAI or Anthropic request formats, and the Qoder executor owns Qoder-specific wire behavior.

## API surface

### Anthropic-compatible endpoints

`/v1/messages` is the priority path for Claude Code.

Supported request fields:

- `model`
- `system`
- `messages`
- `tools`
- `tool_choice`
- `max_tokens`
- `stop_sequences`
- `temperature`
- `top_p`
- `stream`

Supported content blocks:

- `text`
- `tool_use`
- `tool_result`

Images and files are explicitly unsupported in the first version unless a later compatibility test proves a safe conversion. Unsupported blocks should return a clear protocol-specific error or configurable text placeholder behavior.

Streaming responses use Anthropic SSE events:

- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`
- `error`

Tool calls from Qoder are accumulated into Anthropic `tool_use` blocks. Tool results from Claude Code are normalized back into canonical tool-result messages before Qoder payload construction.

### OpenAI-compatible endpoints

`/v1/chat/completions` is delivered in the same first version for Codex/OpenAI clients.

Supported request fields:

- `model`
- `messages`
- `tools`
- `tool_choice`
- `stream`
- `temperature`
- `top_p`
- `max_tokens`
- `stop`

Supported roles:

- `system`
- `user`
- `assistant`
- `tool`

Streaming returns OpenAI chat completion chunks followed by `data: [DONE]`. Non-streaming responses aggregate content, tool calls, finish reason, and usage when available. If upstream usage is not available, usage fields may be zeroed but must remain structurally valid.

`/v1/models` returns local model aliases that map to Qoder model keys/sources. Model aliases should include Claude-friendly and OpenAI/Codex-friendly names so clients can be configured without knowing Qoder internals.

## Canonical protocol model

Both API families convert to the same internal model:

- `CanonicalRequest`: model alias, resolved Qoder model metadata, system text, ordered messages, tools, tool choice, generation options, stream flag, and client protocol.
- `CanonicalMessage`: role, content blocks, tool call references, and metadata.
- `CanonicalContentBlock`: text, tool call, or tool result.
- `CanonicalEvent`: response start, text delta, tool call delta, response metadata, stop, or error.
- `CanonicalError`: stable error code, HTTP status, retryability, account impact, and user-facing message.

This prevents separate OpenAI and Anthropic implementations from drifting. Claude Code compatibility remains the primary validation target, but OpenAI/Codex uses the same conversion core.

## Qoder execution

The Qoder executor ports the proven behavior from the Java prototype:

- Exchange configured PATs or imported credentials for Qoder session material.
- Preserve Qoder encoding, signature, bearer composition, and required `cosy-*` headers.
- Build request payloads from a template equivalent to `baseprompt.json` while replacing per-request IDs, timestamps, model fields, messages, tools, and business metadata.
- Send requests to Qoder SSE generation endpoints.
- Parse upstream SSE lines and convert model deltas and tool-call deltas into canonical events.

The low-level Qoder wire module should be isolated so changes to signing, encoding, or header details do not leak into protocol adapters.

## Account import and pool management

Supported account sources:

1. `PATAccountProvider`: reads one or more Qoder PATs from config or environment and exchanges them for sessions at startup or on demand.
2. `OAuthImportProvider`: CLI starts a temporary localhost callback, opens the browser for authorization, and stores the imported account.
3. `LocalQoderImportProvider`: imports local Qoder login state by following the account-discovery behavior found in the reference desktop project.

All sources produce the same stored account shape:

- Stable account ID and display name.
- Source type.
- Encrypted or file-protected session material.
- Machine/session identifiers needed by Qoder.
- Supported model metadata.
- Latest quota snapshot.
- Health status.
- Failure counters.
- Cooldown deadline.

First-version persistence can use SQLite for structured state or a JSON file if that keeps the implementation substantially simpler. The storage interface must hide that choice from the rest of the system.

## Scheduling strategy

Scheduling is quota-aware by default:

1. Filter accounts by enabled status, health, cooldown, and model support.
2. Prefer accounts with fresh quota data and sufficient remaining quota.
3. Penalize recent failures and accounts close to quota exhaustion.
4. Fall back to health-aware round robin when quota data is unavailable.
5. Mark accounts differently for auth failures, rate limits, quota exhaustion, upstream 5xx, and network failures.

If no account is available, the API returns a protocol-specific error that explains whether the cause is authentication, quota, cooldown, or missing model support.

## CLI and configuration

The project uses `config.yaml` by default and supports environment variable overrides for local scripting.

Default local service settings:

```yaml
server:
  host: 127.0.0.1
  port: 8963
storage:
  path: ./data/qoder-proxy.db
logging:
  level: info
models:
  - alias: claude-sonnet-4-5
    qoder_key: lite
    qoder_source: system
  - alias: gpt-5-codex
    qoder_key: lite
    qoder_source: system
```

Server-deployment fields are reserved but not emphasized in the first version:

- `server.api_keys`
- `server.bind_host`
- `server.trusted_proxies`
- `storage.path`
- `logging.level`

CLI commands:

- `serve`: start the proxy.
- `account add-pat`: add a PAT-backed account.
- `account login`: perform browser authorization import.
- `account import-local`: import local Qoder login state.
- `account list`: list accounts with redacted identifiers and status.
- `account check`: refresh health and quota state.
- `account remove`: remove an account.
- `models list`: show exposed aliases and Qoder mappings.

## Error handling and logging

All layers raise or return `CanonicalError` values. The API layer converts them into Anthropic or OpenAI error formats.

Error categories:

- Invalid client request.
- Unsupported feature.
- Missing or unknown model.
- No available account.
- Authentication failure.
- Rate limited.
- Quota exhausted.
- Qoder upstream error.
- Upstream stream interrupted.
- Internal conversion error.

Logs must redact PATs, bearer payloads, request signatures, machine tokens, refresh tokens, and full account identifiers. Request logs may include short account IDs, model alias, protocol, latency, stream/non-stream mode, and error category.

## Testing and acceptance

Testing is split into three levels:

1. **Unit tests** for protocol conversion, tool-call accumulation, model alias resolution, Qoder event parsing, and scheduler scoring.
2. **Mock upstream tests** that simulate Qoder SSE, auth failure, rate limit, quota exhaustion, malformed events, and interrupted streams.
3. **Manual local acceptance** with real clients:
   - Claude Code pointed at local Anthropic-compatible endpoint.
   - Codex/OpenAI client pointed at local OpenAI-compatible endpoint.
   - Streaming text works.
   - Tool calls and tool results round-trip.
   - Multiple accounts are selected according to quota/health.
   - Errors are understandable in both client protocols.

## Implementation direction

Use Python with FastAPI and async HTTP/SSE handling. Keep modules small and aligned to the architecture layers:

- `api/` for routes and protocol-specific response formatting.
- `adapters/` for Anthropic/OpenAI conversion.
- `canonical/` for internal request, event, and error types.
- `qoder/` for encoding, signing, session acquisition, payload building, and SSE parsing.
- `accounts/` for providers, pool state, quota, health, and scheduling.
- `config/` for loading and model alias resolution.
- `cli/` for service and account commands.
- `tests/` for unit and mock-upstream tests.

This structure keeps the first version lightweight while preserving the option to add Docker/systemd deployment, API key enforcement, a web management UI, and richer quota dashboards later.

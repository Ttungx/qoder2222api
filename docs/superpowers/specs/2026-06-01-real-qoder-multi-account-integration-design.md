# Real Qoder Multi-Account Integration Design

## Goal

Connect the existing mock-compatible proxy to real Qoder upstream execution while preserving local-first safety and the existing Anthropic/OpenAI protocol boundaries.

The next development slice should deliver a complete account/executor architecture with the most reliable paths usable first:

- PAT-backed accounts should support real session exchange and signed Qoder SSE calls.
- Local Qoder account import should be implemented where local state can be discovered safely.
- Browser authorization should have the same provider interface and CLI entrypoint, but may remain a clearly marked adapter if the exact OAuth flow cannot be verified from available references.
- API routes should be able to select mock or real Qoder execution through config.

## Scope

In scope:

- Qoder session context construction from stored account credentials.
- PAT-to-session exchange using Qoder center APIs.
- Signed encoded JSON and SSE requests to Qoder generation endpoints.
- Account storage shape for credentials, session material, supported models, health, quota, and cooldown.
- Account providers for PAT, local import, and browser login interfaces.
- Health/quota-aware account selection and failure classification.
- End-to-end route wiring for Anthropic `/v1/messages` and OpenAI `/v1/chat/completions` through a real executor.
- Tests with mocked Qoder center/upstream HTTP responses by default.
- Opt-in manual tests that require real Qoder credentials.

Out of scope for this slice:

- Public multi-tenant server controls beyond existing optional API keys.
- Web management UI.
- Full OpenAI Responses API.
- Guaranteed completion of browser OAuth if Qoder's current authorization flow cannot be validated locally.
- Logging full tokens, signatures, machine IDs, bearer payloads, or refresh tokens.

## Architecture

### Qoder session layer

Add `qoder/session.py` with data models and builders:

- `AuthIdentity`: normalized identity fields returned by Qoder token exchange or imported local state.
- `MachineIdentity`: machine ID, machine token, and machine type.
- `SessionContext`: temp key, cosy key, encrypted info payload, auth identity, and machine identity.
- `SessionBuilder`: creates session contexts using RSA encryption, AES-CBC encryption, payload base64 construction, and request signature composition compatible with the Java reference.

The session layer owns sensitive material and only exposes redacted summaries to logs/CLI output.

### Qoder auth/client layer

Add `qoder/auth.py` and `qoder/client.py`:

- `QoderAuthClient.exchange_pat(personal_token, machine)` posts the encoded center API payload and returns `AuthIdentity` plus refresh/session material.
- `QoderAuthClient.user_status(...)` and `heartbeat(...)` are available for account check/refresh flows.
- `QoderClient.post_json(...)` and `QoderClient.stream_sse(...)` build encoded request bodies, Qoder headers, bearer signatures, and parse SSE lines.

Network calls use `httpx.AsyncClient`. Default automated tests mock HTTP transport and never require real credentials.

### Qoder executor layer

Add `qoder/executor.py`:

1. Receive a `CanonicalRequest` and selected `Account`.
2. Ensure the account has a fresh `SessionContext`.
3. Build a Qoder payload from canonical messages/tools/model metadata.
4. Stream Qoder SSE events through the signed client.
5. Parse Qoder deltas into `CanonicalEvent` values.
6. Emit canonical errors for upstream failures and interrupted streams.

The executor does not know Anthropic or OpenAI response formats.

### Account providers and pool

Add `accounts/providers.py` and `accounts/pool.py`:

- `PATAccountProvider`: creates/refreshes accounts from stored PAT or `pat_env`.
- `LocalQoderImportProvider`: searches documented local Qoder state locations and imports usable identity/session material when found.
- `OAuthImportProvider`: defines the browser authorization contract and CLI flow; if exact OAuth details are unavailable, it returns a clear unsupported-provider error rather than pretending to work.
- `AccountPool`: loads accounts from storage, refreshes sessions on demand, asks the scheduler for an account, and applies health updates after execution.

Account storage should expand but stay JSON-backed for now. Sensitive fields may be stored as local file-protected plaintext in the first local-only version, with encryption left for a later hardening slice.

## Data flow

### Startup

1. Load config.
2. Load account storage.
3. Build `ModelResolver`, `AccountPool`, scheduler, and executor.
4. If executor mode is `mock`, no account is required.
5. If executor mode is `qoder`, startup validates that at least one enabled account exists, but session exchange can happen lazily on first request.

### Request lifecycle

1. API route parses Anthropic or OpenAI request.
2. Adapter converts it to `CanonicalRequest`.
3. Model alias resolves to Qoder model metadata.
4. If executor mode is `mock`, use the existing mock executor.
5. If executor mode is `qoder`, account pool selects an account for the Qoder model key.
6. Executor streams or aggregates Qoder canonical events.
7. API adapter formats protocol-specific streaming or non-streaming response.
8. Account pool updates account health, cooldown, and quota snapshot based on result/error.

## Configuration and CLI

Config adds:

```yaml
executor:
  mode: mock # mock | qoder
accounts:
  storage_path: ./data/accounts.json
qoder:
  center_base_url: https://center.qoder.sh
  api_base_url: https://api3.qoder.sh
  client_version: 0.1.43
```

CLI additions:

- `account add-pat --name <name> --pat-env QODER_PAT` stores a PAT-backed account without printing the token.
- `account check` refreshes session/health/quota for configured accounts.
- `account remove <id>` removes an account.
- `account import-local` attempts local Qoder state discovery and reports imported account IDs.
- `account login` starts the OAuth provider flow if implemented; otherwise it fails with a clear unsupported message.
- `serve --executor qoder` can override config mode for manual real-upstream testing.

## Error handling

Map Qoder failures into existing canonical error codes:

- 401/invalid token: `authentication_failed`, account requires reauth or is disabled.
- 429/rate limit: `rate_limited`, short cooldown.
- quota exhaustion: `quota_exhausted`, quota cooldown.
- upstream 5xx: `upstream_error`, temporary penalty.
- network timeout/disconnect: `stream_interrupted` or `upstream_error`, retryable penalty.
- no eligible account: `no_available_account`.

Streaming errors should be emitted in the client's protocol-specific SSE error shape when possible.

## Security and logging

Never log full values for:

- PATs
- refresh tokens
- security OAuth tokens
- bearer payloads
- request signatures
- cosy keys
- machine IDs
- machine tokens

CLI output may show short account IDs, display names, source type, health, model support, and redacted token/source hints.

## Testing strategy

Default tests:

- Session encryption/signature construction using deterministic inputs where possible.
- PAT exchange request shape with mocked `httpx` transport.
- Signed Qoder headers and encoded body construction.
- SSE parsing for text deltas, tool-call deltas, malformed events, and stream interruption.
- Account provider/storage/pool refresh behavior.
- Scheduler health/quota/cooldown behavior.
- API integration with mocked real executor path.

Manual opt-in tests:

- Require `QODER_PROXY_REAL_TESTS=1` and a real PAT environment variable.
- Exercise PAT exchange, simple Anthropic request, simple OpenAI request, and streaming response.
- Must redact all sensitive values in output.

## Acceptance criteria

The slice is acceptable when:

- `executor.mode: mock` continues to pass all existing tests and local curl checks.
- `executor.mode: qoder` can select a configured PAT account and attempt a signed Qoder SSE request.
- If real credentials are provided, a simple text prompt can flow through `/v1/messages` and `/v1/chat/completions`.
- Account health changes after auth/rate/quota/upstream/network errors.
- Local import and OAuth commands exist with honest success/unsupported behavior.
- No default test requires real credentials or network access.
- `python -m pytest` and `python -m ruff check .` pass.

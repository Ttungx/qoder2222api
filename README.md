# Qoder Proxy

Lightweight Python reverse proxy for exposing Qoder-backed models through Anthropic-compatible and OpenAI-compatible API surfaces.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Commands

```bash
python -m qoder_proxy.cli.main --help
python -m qoder_proxy.cli.main config init --print
python -m qoder_proxy.cli.main models list
python -m qoder_proxy.cli.main serve --host 127.0.0.1 --port 8963
```

## Validation

```bash
python -m pytest
python -m ruff check .
```

The current implementation includes Anthropic-compatible `/v1/messages`, OpenAI-compatible `/v1/chat/completions`, `/v1/models`, config/model aliases, JSON account storage, account scheduling primitives, Qoder wire helpers, and a mock executor. Real Qoder credential exchange and upstream execution are scaffolded at the module boundary but are not enabled by default.

## Client configuration

### Claude Code

Point Claude Code at the local Anthropic-compatible server using the model alias from config, for example `claude-sonnet-4-5`. If `server.api_keys` is configured, send the configured key as a bearer token.

### OpenAI/Codex-compatible clients

Use this base URL:

```text
http://127.0.0.1:8963/v1
```

Use a configured model alias such as `gpt-5-codex`. The first complete route is `/v1/chat/completions`; OpenAI Responses API is intentionally out of scope for now.

## Known limitations

- Real Qoder upstream calls still require wiring account sessions into an executor.
- Browser login and local Qoder account import are CLI placeholders for later completion.
- Image/file content blocks are rejected or unsupported in the first version.
- Public multi-tenant server operation is out of scope; only optional local API-key protection is provided.

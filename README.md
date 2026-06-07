# Qoder Proxy

一个轻量级的 Python 反向代理，将 Qoder 后端的模型通过 Anthropic 兼容和 OpenAI 兼容的 API 表面暴露出来。

## 本地安装

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## 常用命令

```bash
python -m qoder_proxy.cli.main --help
python -m qoder_proxy.cli.main config init --print
python -m qoder_proxy.cli.main models list
python -m qoder_proxy.cli.main serve --host 127.0.0.1 --port 8963
```

服务启动后访问 `http://127.0.0.1:8963/` 即可打开 Web Dashboard。

## 测试与校验

```bash
python -m pytest
python -m ruff check .
```

当前实现包括：Anthropic 兼容的 `/v1/messages`、OpenAI 兼容的 `/v1/chat/completions`、`/v1/models`，配置/模型别名、JSON 账户存储、账户调度原语、Qoder 协议底层辅助模块，以及一个 Mock 执行器。真实 Qoder 凭证交换与上游执行已在模块边界完成脚手架，但默认未启用。

## 真实 Qoder 执行器模式

Mock 模式为默认模式，无需任何凭证：

```bash
python -m qoder_proxy.cli.main serve --host 127.0.0.1 --port 8963
```

添加一个基于 PAT 的账户（不直接存储 token）：

```bash
export QODER_PAT=<你的-token>
python -m qoder_proxy.cli.main account add-pat --name main --pat-env QODER_PAT
python -m qoder_proxy.cli.main account list
```

或在 Dashboard 中通过 OAuth 设备流登录，会自动保存会话。

在 `config.yaml` 中启用真实执行器模式：

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

默认的测试不会连接 Qoder。任何真实账户相关的测试必须显式开启，并且在输出中对 token、机器标识、签名和 bearer 载荷进行脱敏处理。

## 客户端配置

### Claude Code

将 Claude Code 指向本地的 Anthropic 兼容服务，使用配置中的模型别名，例如 `claude-sonnet-4-5`。如果配置了 `server.api_keys`，请将配置的 key 作为 bearer token 发送。

### OpenAI / Codex 兼容客户端

使用以下 base URL：

```text
http://127.0.0.1:8963/v1
```

使用配置好的模型别名，例如 `gpt-5-codex`。首个完整路由是 `/v1/chat/completions`；OpenAI Responses API 当前不在支持范围内。

## Web Dashboard

服务启动后，访问 `http://127.0.0.1:8963/` 即可使用 Web Dashboard。包含以下页面：

- **总览**：服务状态、运行时长、累计请求数与成功率、按模型分组的请求统计
- **模型**：列出配置中和运行时注册的模型别名，支持新增/删除运行时别名
- **账户**：查看账户健康度、冷却时间，支持新增 PAT 账户、删除、启停、重置健康状态、触发 OAuth 设备流登录、导入本地 Qoder 账户
- **接口**：展示可用的 API 路由与调用方式

支持 `Ctrl/⌘ + K` 全局命令面板。

## 已知限制

- 真实 Qoder 上游调用仍需要把账户会话接入到执行器（首版已基本完成，多账户调度仍处于早期阶段）。
- 部分 CLI 占位命令（如浏览器登录的细节流程）尚需完善。
- 图片/文件内容块在首版中被拒绝或不支持。
- 公开的多租户服务运行不在支持范围内；仅提供可选的本地 API Key 鉴权。

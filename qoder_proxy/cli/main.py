import argparse
from pathlib import Path
from uuid import uuid4

import uvicorn

from qoder_proxy.accounts import Account, JsonAccountStorage
from qoder_proxy.config import ModelResolver, default_config_yaml, load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="qoder-proxy", description="Qoder reverse proxy CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the proxy server.")
    serve_parser.add_argument("--config", "-c", type=Path)
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    serve_parser.set_defaults(handler=_serve)

    config_parser = subparsers.add_parser("config", help="Manage config files.")
    config_subparsers = config_parser.add_subparsers(dest="config_command", required=True)
    config_init_parser = config_subparsers.add_parser("init", help="Create a default config.")
    config_init_parser.add_argument("--output", "-o", type=Path, default=Path("config.yaml"))
    config_init_parser.add_argument("--print", action="store_true", dest="print_config")
    config_init_parser.set_defaults(handler=_config_init)

    models_parser = subparsers.add_parser("models", help="Inspect model aliases.")
    models_subparsers = models_parser.add_subparsers(dest="models_command", required=True)
    models_list_parser = models_subparsers.add_parser("list", help="List configured model aliases.")
    models_list_parser.add_argument("--config", "-c", type=Path)
    models_list_parser.set_defaults(handler=_models_list)

    account_parser = subparsers.add_parser("account", help="Manage Qoder accounts.")
    account_subparsers = account_parser.add_subparsers(dest="account_command", required=True)
    account_add_pat_parser = account_subparsers.add_parser("add-pat", help="Add a PAT account.")
    account_add_pat_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_add_pat_parser.add_argument("--name", required=True)
    account_add_pat_parser.add_argument("--pat")
    account_add_pat_parser.add_argument("--pat-env")
    account_add_pat_parser.set_defaults(handler=_account_add_pat)
    account_list_parser = account_subparsers.add_parser("list", help="List accounts.")
    account_list_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_list_parser.set_defaults(handler=_account_list)

    args = parser.parse_args()
    args.handler(args)


def _serve(args: argparse.Namespace) -> None:
    proxy_config = load_config(args.config)
    uvicorn.run(
        "qoder_proxy.api.app:create_app",
        factory=True,
        host=args.host or proxy_config.server.host,
        port=args.port or proxy_config.server.port,
    )


def _config_init(args: argparse.Namespace) -> None:
    content = default_config_yaml()
    if args.print_config:
        print(content, end="")
        return
    if args.output.exists():
        raise SystemExit(f"Config already exists: {args.output}")
    args.output.write_text(content, encoding="utf-8")
    print(f"Wrote {args.output}")


def _models_list(args: argparse.Namespace) -> None:
    resolver = ModelResolver(load_config(args.config).models)
    for model in resolver.list_models():
        print(f"{model.alias}\t{model.qoder_key}\t{model.qoder_source}")


def _account_add_pat(args: argparse.Namespace) -> None:
    if not args.pat and not args.pat_env:
        raise SystemExit("Provide --pat or --pat-env")
    account = Account(
        id=f"acct_{uuid4().hex[:12]}",
        display_name=args.name,
        source="pat",
        pat=args.pat,
        pat_env=args.pat_env,
    )
    JsonAccountStorage(args.storage).save(account)
    print(f"Added account {account.display_name} ({account.id})")


def _account_list(args: argparse.Namespace) -> None:
    accounts = JsonAccountStorage(args.storage).list()
    if not accounts:
        print("No accounts configured.")
        return
    for account in accounts:
        print(f"{account.id}\t{account.display_name}\t{account.source}\t{account.health}")


if __name__ == "__main__":
    main()

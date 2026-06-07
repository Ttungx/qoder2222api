import argparse
import os
from pathlib import Path
from uuid import uuid4

import uvicorn

from qoder_proxy.accounts import Account, JsonAccountStorage, LocalQoderImportProvider
from qoder_proxy.config import ModelResolver, default_config_yaml, load_config


def main() -> None:
    parser = argparse.ArgumentParser(prog="qoder-proxy", description="Qoder reverse proxy CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the proxy server.")
    serve_parser.add_argument("--config", "-c", type=Path)
    serve_parser.add_argument("--host")
    serve_parser.add_argument("--port", type=int)
    serve_parser.add_argument("--executor", choices=["mock", "qoder"])
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
    account_remove_parser = account_subparsers.add_parser("remove", help="Remove an account.")
    account_remove_parser.add_argument("account_id")
    account_remove_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_remove_parser.set_defaults(handler=_account_remove)
    account_login_parser = account_subparsers.add_parser(
        "login",
        help="Browser authorization import.",
    )
    account_login_parser.set_defaults(handler=_account_login)
    account_import_local_parser = account_subparsers.add_parser(
        "import-local",
        help="Import local Qoder account state.",
    )
    account_import_local_parser.add_argument(
        "--storage",
        type=Path,
        default=Path("data/accounts.json"),
    )
    account_import_local_parser.set_defaults(handler=_account_import_local)
    account_check_parser = account_subparsers.add_parser("check", help="Check configured accounts.")
    account_check_parser.add_argument("--storage", type=Path, default=Path("data/accounts.json"))
    account_check_parser.set_defaults(handler=_account_check)

    args = parser.parse_args()
    args.handler(args)


def _serve(args: argparse.Namespace) -> None:
    proxy_config = load_config(args.config)
    if args.executor:
        proxy_config.executor.mode = args.executor
    # Pass executor mode via env var so factory-based create_app() picks it up
    os.environ["QODER_PROXY_EXECUTOR"] = proxy_config.executor.mode
    if args.host:
        os.environ["QODER_PROXY_HOST"] = args.host
    if args.port:
        os.environ["QODER_PROXY_PORT"] = str(args.port)
    if proxy_config.executor.mode == "qoder":
        print(f"[qoder-proxy] Starting in Qoder executor mode on "
              f"{proxy_config.server.host}:{proxy_config.server.port}")
    uvicorn.run(
        "qoder_proxy.api.app:create_app",
        factory=True,
        host=proxy_config.server.host,
        port=proxy_config.server.port,
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


def _account_remove(args: argparse.Namespace) -> None:
    JsonAccountStorage(args.storage).remove(args.account_id)
    print(f"Removed account {args.account_id}")


def _account_login(args: argparse.Namespace) -> None:
    print("Browser login is not implemented for this Qoder flow yet")
    raise SystemExit(1)


def _account_import_local(args: argparse.Namespace) -> None:
    storage = JsonAccountStorage(args.storage)
    accounts = LocalQoderImportProvider().import_accounts()
    for account in accounts:
        storage.save(account)
    print(f"Imported {len(accounts)} local account(s)")


def _account_check(args: argparse.Namespace) -> None:
    accounts = JsonAccountStorage(args.storage).list()
    for account in accounts:
        print(f"{account.id}\t{account.display_name}\t{account.health}")


if __name__ == "__main__":
    main()

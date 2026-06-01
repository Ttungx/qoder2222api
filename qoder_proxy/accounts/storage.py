import json
from pathlib import Path

from qoder_proxy.accounts.models import Account


class JsonAccountStorage:
    def __init__(self, path: Path) -> None:
        self.path = path

    def list(self) -> list[Account]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Account.model_validate(item) for item in data.get("accounts", [])]

    def get(self, account_id: str) -> Account:
        for account in self.list():
            if account.id == account_id:
                return account
        raise KeyError(account_id)

    def save(self, account: Account) -> None:
        accounts = [item for item in self.list() if item.id != account.id]
        accounts.append(account)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"accounts": [_stored_account(item) for item in accounts]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def remove(self, account_id: str) -> None:
        accounts = [item for item in self.list() if item.id != account_id]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {"accounts": [_stored_account(item) for item in accounts]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


def _stored_account(account: Account) -> dict[str, object]:
    data = account.model_dump(mode="json")
    data["pat"] = None
    data["session_info"] = None
    data["session_cosy_key"] = None
    if data.get("identity"):
        data["identity"]["security_oauth_token"] = ""
        data["identity"]["refresh_token"] = ""
    if data.get("machine"):
        data["machine"]["machine_id"] = ""
        data["machine"]["machine_token"] = ""
    return data

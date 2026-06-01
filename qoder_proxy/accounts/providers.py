import json
import os
from pathlib import Path
from uuid import uuid4

from qoder_proxy.accounts.models import Account
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


class PATAccountProvider:
    def __init__(self, auth_client) -> None:
        self.auth_client = auth_client

    async def refresh(self, account: Account) -> Account:
        token = account.pat or (os.getenv(account.pat_env) if account.pat_env else None)
        if not token:
            raise ValueError(f"No PAT available for account {account.id}")
        machine = account.machine or _new_machine()
        identity = await self.auth_client.exchange_pat(token, machine)
        session = SessionBuilder.new_session(identity, machine)
        return account.model_copy(
            update={
                "identity": identity,
                "machine": machine,
                "session_info": session.info,
                "session_cosy_key": session.cosy_key,
            }
        )


class LocalQoderImportProvider:
    def __init__(self, search_paths: list[Path] | None = None) -> None:
        self.search_paths = search_paths or _default_local_paths()

    def import_accounts(self) -> list[Account]:
        accounts: list[Account] = []
        for root in self.search_paths:
            state = root / "qoder-account.json"
            if not state.exists():
                continue
            data = json.loads(state.read_text(encoding="utf-8"))
            identity = AuthIdentity(
                name=str(data.get("name", "")),
                aid=str(data.get("id", "")),
                uid=str(data.get("id", "")),
                user_type=str(data.get("userType", "personal_standard")),
                security_oauth_token=str(data.get("securityOauthToken", "")),
                refresh_token=str(data.get("refreshToken", "")),
            )
            accounts.append(
                Account(
                    id=f"acct_{uuid4().hex[:12]}",
                    display_name=identity.name or identity.uid,
                    source="local",
                    identity=identity,
                    machine=_new_machine(),
                )
            )
        return accounts


class OAuthImportProvider:
    def login(self) -> Account:
        raise NotImplementedError("Browser login is not implemented for this Qoder flow yet")


def _new_machine() -> MachineIdentity:
    return MachineIdentity(
        machine_id=str(uuid4()),
        machine_token=uuid4().hex + uuid4().hex,
        machine_type=uuid4().hex[:18],
    )


def _default_local_paths() -> list[Path]:
    home = Path.home()
    return [
        home / ".qoder",
        home / ".config" / "qoder",
        home / "AppData" / "Roaming" / "Qoder",
    ]

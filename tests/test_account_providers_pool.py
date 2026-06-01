import asyncio
from pathlib import Path

import pytest

from qoder_proxy.accounts.models import Account
from qoder_proxy.accounts.providers import (
    LocalQoderImportProvider,
    OAuthImportProvider,
    PATAccountProvider,
)
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity


class FakeAuthClient:
    async def exchange_pat(self, personal_token: str, machine: MachineIdentity) -> AuthIdentity:
        assert personal_token == "pat-secret"
        return AuthIdentity(
            name="User",
            aid="user-1",
            uid="user-1",
            user_type="personal_standard",
            security_oauth_token="oauth-token",
            refresh_token="refresh-token",
        )


def test_pat_provider_refreshes_identity_from_pat_env(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        monkeypatch.setenv("QODER_PAT", "pat-secret")
        account = Account(id="acct_1", display_name="main", source="pat", pat_env="QODER_PAT")

        refreshed = await PATAccountProvider(FakeAuthClient()).refresh(account)

        assert refreshed.identity.uid == "user-1"
        assert refreshed.identity.security_oauth_token == "oauth-token"
        assert refreshed.machine.machine_id
        assert refreshed.machine.machine_token
        assert refreshed.machine.machine_type

    asyncio.run(run())


def test_local_import_provider_reads_json_identity(tmp_path: Path) -> None:
    state = tmp_path / "qoder-account.json"
    state.write_text(
        '{"name":"Local","id":"local-1","securityOauthToken":"oauth","refreshToken":"refresh"}',
        encoding="utf-8",
    )

    accounts = LocalQoderImportProvider([tmp_path]).import_accounts()

    assert len(accounts) == 1
    assert accounts[0].display_name == "Local"
    assert accounts[0].identity.uid == "local-1"


def test_oauth_provider_reports_unsupported() -> None:
    with pytest.raises(NotImplementedError, match="Browser login is not implemented"):
        OAuthImportProvider().login()

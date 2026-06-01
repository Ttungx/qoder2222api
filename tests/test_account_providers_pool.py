import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qoder_proxy.accounts.models import Account, AccountHealth
from qoder_proxy.accounts.pool import AccountPool
from qoder_proxy.accounts.providers import (
    LocalQoderImportProvider,
    OAuthImportProvider,
    PATAccountProvider,
)
from qoder_proxy.accounts.scheduler import AccountScheduler
from qoder_proxy.accounts.storage import JsonAccountStorage
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.session import AuthIdentity, MachineIdentity, SessionBuilder


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
        assert refreshed.session_info
        assert refreshed.session_cosy_key

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


def test_account_pool_selects_and_refreshes_pat_account(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def run() -> None:
        monkeypatch.setenv("QODER_PAT", "pat-secret")
        storage = JsonAccountStorage(tmp_path / "accounts.json")
        storage.save(
            Account(
                id="acct_1",
                display_name="main",
                source="pat",
                pat_env="QODER_PAT",
                supported_models=["lite"],
            )
        )
        pool = AccountPool(
            storage=storage,
            scheduler_factory=AccountScheduler,
            pat_provider=PATAccountProvider(FakeAuthClient()),
        )

        account = await pool.select_for_model("lite")

        assert account.id == "acct_1"
        assert account.identity.uid == "user-1"
        assert account.session_info
        assert account.session_cosy_key
        assert storage.get("acct_1").identity.uid == "user-1"
        assert storage.get("acct_1").session_info is None

        account = await pool.select_for_model("lite")
        assert account.session_info
        assert account.session_cosy_key

    asyncio.run(run())


def test_account_pool_marks_auth_failure_disabled(tmp_path: Path) -> None:
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    storage.save(Account(id="acct_1", display_name="main", source="pat"))
    pool = AccountPool(storage=storage, scheduler_factory=AccountScheduler)

    pool.apply_error(
        "acct_1",
        CanonicalError(ErrorCode.AUTHENTICATION_FAILED, "bad", http_status=401),
    )

    account = storage.get("acct_1")
    assert account.enabled is False
    assert account.health is AccountHealth.AUTH_FAILED


def test_account_pool_marks_rate_limit_cooldown(tmp_path: Path) -> None:
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    storage.save(Account(id="acct_1", display_name="main", source="pat"))
    pool = AccountPool(storage=storage, scheduler_factory=AccountScheduler)

    pool.apply_error("acct_1", CanonicalError(ErrorCode.RATE_LIMITED, "slow", http_status=429))

    account = storage.get("acct_1")
    assert account.enabled is True
    assert account.health is AccountHealth.RATE_LIMITED
    assert account.cooldown_until > datetime.now(UTC) + timedelta(seconds=1)


def test_scheduler_reuses_transient_error_account_after_cooldown() -> None:
    account = Account(
        id="acct_1",
        display_name="main",
        source="pat",
        health=AccountHealth.RATE_LIMITED,
        cooldown_until=datetime.now(UTC) - timedelta(seconds=1),
    )

    selected = AccountScheduler([account]).select("lite")

    assert selected.id == "acct_1"


def test_account_storage_redacts_sensitive_fields(tmp_path: Path) -> None:
    identity = AuthIdentity(
        uid="user-1",
        security_oauth_token="oauth-token",
        refresh_token="refresh-token",
    )
    machine = MachineIdentity(machine_id="mid", machine_token="mtok", machine_type="mtype")
    session = SessionBuilder.new_session(identity, machine, temp_key=b"1234567890abcdef")
    storage = JsonAccountStorage(tmp_path / "accounts.json")

    storage.save(
        Account(
            id="acct_1",
            display_name="main",
            source="pat",
            pat="pat-secret",
            identity=identity,
            machine=machine,
            session_info=session.info,
            session_cosy_key=session.cosy_key,
        )
    )

    raw = (tmp_path / "accounts.json").read_text(encoding="utf-8")

    assert "pat-secret" not in raw
    assert "oauth-token" not in raw
    assert "refresh-token" not in raw
    assert session.info not in raw
    assert session.cosy_key not in raw

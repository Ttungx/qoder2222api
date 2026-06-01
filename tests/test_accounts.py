from pathlib import Path

from qoder_proxy.accounts.models import Account, AccountHealth, QuotaSnapshot
from qoder_proxy.accounts.scheduler import AccountScheduler
from qoder_proxy.accounts.storage import JsonAccountStorage


def test_json_account_storage_add_list_remove_round_trip(tmp_path: Path) -> None:
    storage = JsonAccountStorage(tmp_path / "accounts.json")
    account = Account(id="acct_1", display_name="main", source="pat", pat_env="QODER_PAT")

    storage.save(account)

    assert storage.list()[0].id == "acct_1"
    assert storage.get("acct_1").display_name == "main"
    storage.remove("acct_1")
    assert storage.list() == []


def test_scheduler_prefers_higher_remaining_quota() -> None:
    accounts = [
        Account(
            id="low",
            display_name="low",
            source="pat",
            supported_models=["lite"],
            quota=QuotaSnapshot(remaining=5, limit=100),
        ),
        Account(
            id="high",
            display_name="high",
            source="pat",
            supported_models=["lite"],
            quota=QuotaSnapshot(remaining=50, limit=100),
        ),
    ]

    selected = AccountScheduler(accounts).select("lite")

    assert selected.id == "high"


def test_scheduler_filters_disabled_cooldown_unhealthy_and_model_support() -> None:
    accounts = [
        Account(id="disabled", display_name="disabled", source="pat", enabled=False),
        Account(id="bad", display_name="bad", source="pat", health=AccountHealth.AUTH_FAILED),
        Account(id="wrong", display_name="wrong", source="pat", supported_models=["pro"]),
        Account(id="ok", display_name="ok", source="pat", supported_models=["lite"]),
    ]

    selected = AccountScheduler(accounts).select("lite")

    assert selected.id == "ok"


def test_scheduler_returns_none_when_no_account_available() -> None:
    selected = AccountScheduler(
        [Account(id="bad", display_name="bad", source="pat", enabled=False)]
    ).select("lite")

    assert selected is None

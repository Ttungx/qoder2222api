from datetime import UTC, datetime

from qoder_proxy.accounts.models import Account, AccountHealth


class AccountScheduler:
    def __init__(self, accounts: list[Account]) -> None:
        self.accounts = accounts
        self._round_robin_index = 0

    def select(self, qoder_key: str) -> Account | None:
        candidates = [account for account in self.accounts if _available(account, qoder_key)]
        if not candidates:
            return None
        with_quota = [
            account
            for account in candidates
            if account.quota and account.quota.remaining is not None
        ]
        if with_quota:
            return max(with_quota, key=lambda account: account.quota.remaining or 0)
        selected = candidates[self._round_robin_index % len(candidates)]
        self._round_robin_index += 1
        return selected


def _available(account: Account, qoder_key: str) -> bool:
    if not account.enabled:
        return False
    if account.health is not AccountHealth.OK:
        return False
    if account.cooldown_until and account.cooldown_until > datetime.now(UTC):
        return False
    return account.supports_model(qoder_key)

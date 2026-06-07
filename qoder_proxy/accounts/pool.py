from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from qoder_proxy.accounts.models import Account, AccountHealth
from qoder_proxy.accounts.providers import PATAccountProvider
from qoder_proxy.accounts.scheduler import AccountScheduler
from qoder_proxy.accounts.storage import JsonAccountStorage
from qoder_proxy.canonical.errors import CanonicalError, ErrorCode
from qoder_proxy.qoder.session import SessionBuilder


class AccountPool:
    def __init__(
        self,
        *,
        storage: JsonAccountStorage,
        scheduler_factory: Callable[[list[Account]], AccountScheduler] = AccountScheduler,
        pat_provider: PATAccountProvider | None = None,
    ) -> None:
        self.storage = storage
        self.scheduler_factory = scheduler_factory
        self.pat_provider = pat_provider

    async def select_for_model(self, qoder_key: str) -> Account:
        scheduler = self.scheduler_factory(self.storage.list())
        account = scheduler.select(qoder_key)
        if account is None:
            raise CanonicalError(
                ErrorCode.NO_AVAILABLE_ACCOUNT,
                f"No available Qoder account for model {qoder_key}",
                http_status=503,
                retryable=True,
            )
        if account.source == "pat" and (
            account.identity is None or not account.session_info or not account.session_cosy_key
        ):
            if self.pat_provider is None:
                raise CanonicalError(
                    ErrorCode.AUTHENTICATION_FAILED,
                    "PAT account cannot refresh without auth provider",
                    http_status=401,
                )
            account = await self.pat_provider.refresh(account)
            self.storage.save(account)
        elif account.source != "pat" and (
            not account.session_info or not account.session_cosy_key
        ):
            # OAuth / local accounts: rebuild session from persisted identity
            if account.identity is not None and account.machine is not None:
                session = SessionBuilder.new_session(account.identity, account.machine)
                account = account.model_copy(
                    update={
                        "session_info": session.info,
                        "session_cosy_key": session.cosy_key,
                    }
                )
                self.storage.save(account)
            else:
                raise CanonicalError(
                    ErrorCode.AUTHENTICATION_FAILED,
                    f"Account {account.id} has no identity/machine for session rebuild",
                    http_status=401,
                )
        return account

    def apply_success(self, account_id: str) -> None:
        account = self.storage.get(account_id)
        self.storage.save(
            account.model_copy(
                update={"health": AccountHealth.OK, "failure_count": 0, "cooldown_until": None}
            )
        )

    def apply_error(self, account_id: str, error: CanonicalError) -> None:
        account = self.storage.get(account_id)
        updates = {"failure_count": account.failure_count + 1}
        if error.code is ErrorCode.AUTHENTICATION_FAILED:
            updates.update({"enabled": False, "health": AccountHealth.AUTH_FAILED})
        elif error.code is ErrorCode.RATE_LIMITED:
            updates.update(
                {
                    "health": AccountHealth.RATE_LIMITED,
                    "cooldown_until": datetime.now(UTC) + timedelta(seconds=30),
                }
            )
        elif error.code is ErrorCode.QUOTA_EXHAUSTED:
            updates.update(
                {
                    "health": AccountHealth.QUOTA_EXHAUSTED,
                    "cooldown_until": datetime.now(UTC) + timedelta(hours=1),
                }
            )
        else:
            updates.update(
                {
                    "health": AccountHealth.UPSTREAM_ERROR,
                    "cooldown_until": datetime.now(UTC) + timedelta(seconds=10),
                }
            )
        self.storage.save(account.model_copy(update=updates))

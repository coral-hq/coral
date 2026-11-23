"""Sign-in providers the API tests share."""

from __future__ import annotations

from starlette.requests import HTTPConnection

from omnigent.db.account_authority import bind_account_authority, clear_account_authority
from omnigent.server.auth import AuthProvider

HEADER = "X-Forwarded-Email"


class _CrossedAccount(AuthProvider):
    """Signs the ``HEADER`` user in under another user's account, which Coral refuses (403)."""

    def get_user_id(self, request: HTTPConnection) -> str | None:
        clear_account_authority()
        user = request.headers.get(HEADER)
        if user is not None:
            bind_account_authority(f"other-than-{user}", "g1")
        return user


CROSSED_ACCOUNT = _CrossedAccount()

# CORAL(S106): registration carriers move a plugin's rows when a generation rotates.
"""Registration carriers run inside a password change's rotation, never on re-creation."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from omnigent.db.db_models import SqlHost, SqlUser, current_workspace_id
from omnigent.server import accounts_store
from omnigent.server.accounts_store import SqlAlchemyAccountStore, register_registration_carrier
from omnigent.stores.host_store import HostStore

ALICE = "alice"


@pytest.fixture
def accounts(db_uri: str) -> Iterator[SqlAlchemyAccountStore]:
    store = SqlAlchemyAccountStore(db_uri)
    store.create_user_with_password(ALICE, "hash-1")
    yield store
    assert accounts_store._registration_carriers == ()


def _generation(store: SqlAlchemyAccountStore) -> str | None:
    account = store.get_user(ALICE)
    assert account is not None
    return account.account_generation


def test_a_carrier_runs_in_the_rotation_transaction_after_tasks_and_hosts_move(
    db_uri: str, accounts: SqlAlchemyAccountStore
) -> None:
    hosts = HostStore(db_uri)
    host_id = uuid.uuid4().hex
    hosts.upsert_on_connect(host_id, "laptop", ALICE)
    old = _generation(accounts)
    seen: list[tuple[str, str, str, str | None, str | None]] = []

    def carrier(session: Session, user_id: str, before: str, after: str) -> None:
        # Through the rotation's session: the account row is not updated yet, the host is.
        workspace_id = current_workspace_id()
        account = session.execute(
            select(SqlUser.account_generation).where(
                SqlUser.workspace_id == workspace_id, SqlUser.id == user_id
            )
        ).scalar_one()
        host = session.execute(
            select(SqlHost.account_generation).where(
                SqlHost.workspace_id == workspace_id, SqlHost.host_id == host_id
            )
        ).scalar_one()
        seen.append((user_id, before, after, account, host))

    unregister = register_registration_carrier(carrier)
    try:
        new = accounts.update_password(ALICE, "hash-2", revoke_sessions=True)
    finally:
        unregister()

    assert new is not None and new != old
    assert seen == [(ALICE, old, new, old, new)]
    host = hosts.get_host(host_id)
    assert host is not None and host.account_generation == new


def test_a_failing_carrier_aborts_the_rotation(
    db_uri: str, accounts: SqlAlchemyAccountStore
) -> None:
    hosts = HostStore(db_uri)
    host_id = uuid.uuid4().hex
    hosts.upsert_on_connect(host_id, "laptop", ALICE)
    old = _generation(accounts)

    def carrier(_session: Session, _user_id: str, _old: str, _new: str) -> None:
        raise RuntimeError("carrier failed")

    unregister = register_registration_carrier(carrier)
    try:
        with pytest.raises(RuntimeError, match="carrier failed"):
            accounts.update_password(ALICE, "hash-2", revoke_sessions=True)
    finally:
        unregister()

    # Neither the account nor the host moved: the rotation rolled back as one.
    host = hosts.get_host(host_id)
    assert (_generation(accounts), host.account_generation if host else None) == (old, old)
    assert accounts.get_password_hash(ALICE) == "hash-1"


def test_no_carrier_runs_without_a_rotation_or_on_re_creation(
    accounts: SqlAlchemyAccountStore,
) -> None:
    calls: list[str] = []
    unregister = register_registration_carrier(lambda _s, user_id, _o, _n: calls.append(user_id))
    try:
        accounts.update_password(ALICE, "hash-2")
        assert accounts.delete_user(ALICE) is True
        accounts.create_user_with_password(ALICE, "hash-3")
        # A passwordless identity's first generation is provisioned, not rotated.
        accounts.update_password("bob", "hash-4", revoke_sessions=True)
    finally:
        unregister()

    assert calls == []


def test_an_unregister_removes_only_its_own_registration(
    accounts: SqlAlchemyAccountStore,
) -> None:
    calls: list[str] = []

    def carrier(_session: Session, _user_id: str, _old: str, _new: str) -> None:
        calls.append("carried")

    first = register_registration_carrier(carrier)
    second = register_registration_carrier(carrier)
    first()
    first()
    try:
        accounts.update_password(ALICE, "hash-2", revoke_sessions=True)
    finally:
        second()

    assert calls == ["carried"]

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from clr.local_store import initialize_workspace
from clr.private_workspace_access import (
    apply_access_schema,
    create_user,
    grant_membership,
)


ROOT = Path(__file__).resolve().parents[1]


def _cli_module():
    path = ROOT / "scripts" / "manage_private_workspace_users.py"
    spec = spec_from_file_location("manage_private_workspace_users", path)
    module = module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path):
    root = tmp_path / "private_data"
    initialize_workspace(
        root,
        ROOT / "migrations" / "000_local_private_data_plane.sql",
    )
    apply_access_schema(
        root,
        ROOT / "migrations" / "001_private_workspace_access.sql",
    )
    return root


def test_cli_operator_identity_becomes_mandatory_after_admin_bootstrap(tmp_path):
    cli = _cli_module()
    root = _workspace(tmp_path)

    assert cli._actor_user_id(
        root,
        None,
        bootstrap_allowed=True,
    ) is None

    admin = create_user(
        root,
        username="bootstrap-admin",
        password="synthetic-long-password",
        iterations=100_000,
    )
    grant_membership(
        root,
        user_id=admin["user_id"],
        tenant_key="TENANT_A",
        role="ADMIN",
    )

    with pytest.raises(SystemExit, match="actor-username"):
        cli._actor_user_id(
            root,
            None,
            bootstrap_allowed=True,
        )

    assert cli._actor_user_id(
        root,
        "bootstrap-admin",
        bootstrap_allowed=False,
    ) == admin["user_id"]

    analyst = create_user(
        root,
        username="not-admin",
        password="synthetic-long-password",
        iterations=100_000,
        actor_user_id=admin["user_id"],
    )
    grant_membership(
        root,
        user_id=analyst["user_id"],
        tenant_key="TENANT_A",
        role="ANALYST",
        actor_user_id=admin["user_id"],
    )
    with pytest.raises(SystemExit, match="active ADMIN"):
        cli._actor_user_id(
            root,
            "not-admin",
            bootstrap_allowed=False,
        )

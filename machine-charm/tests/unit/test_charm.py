# Copyright 2026 Vítor Zeni
# See LICENSE file for licensing details.
#
# To learn more about testing, see https://canonical.com/juju/docs/ops/latest/explanation/testing/

from unittest import mock

import pytest
from ops import testing

from charm import OnboardingAppMachineCharm


@pytest.fixture
def workload(monkeypatch: pytest.MonkeyPatch):
    """Replace the snap-managing module so tests never touch snapd."""
    fake = mock.MagicMock(PORT=8000)
    fake.get_version.return_value = "0.1"
    monkeypatch.setattr("charm.onboarding_app", fake)
    return fake


def test_blocked_without_database(workload):
    ctx = testing.Context(OnboardingAppMachineCharm)
    state_out = ctx.run(ctx.on.start(), testing.State())
    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")
    workload.configure.assert_not_called()


def test_waiting_until_credentials_arrive(workload):
    ctx = testing.Context(OnboardingAppMachineCharm)
    relation = testing.Relation("database", remote_app_name="postgresql")
    state_out = ctx.run(ctx.on.start(), testing.State(relations={relation}))
    assert state_out.unit_status == testing.WaitingStatus("waiting for database credentials")


def test_active_when_database_ready(workload):
    ctx = testing.Context(OnboardingAppMachineCharm)
    relation = testing.Relation(
        "database",
        remote_app_name="postgresql",
        remote_app_data={
            "endpoints": "10.0.0.5:5432",
            "username": "relation-1",
            "password": "p@ss/word",
            "database": "onboarding",
        },
    )
    state_out = ctx.run(ctx.on.update_status(), testing.State(relations={relation}))
    assert state_out.unit_status == testing.ActiveStatus()
    workload.configure.assert_called_once_with(
        "postgresql://relation-1:p%40ss%2Fword@10.0.0.5:5432/onboarding"
    )
    workload.migrate.assert_called_once()
    assert testing.TCPPort(8000) in state_out.opened_ports


def test_relation_broken_unconfigures(workload):
    ctx = testing.Context(OnboardingAppMachineCharm)
    relation = testing.Relation("database", remote_app_name="postgresql")
    state_out = ctx.run(ctx.on.relation_broken(relation), testing.State(relations={relation}))
    workload.unconfigure.assert_called_once()
    assert state_out.unit_status == testing.BlockedStatus("waiting for database relation")

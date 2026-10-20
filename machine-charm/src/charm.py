#!/usr/bin/env python3
# Copyright 2026 Vítor Zeni
# See LICENSE file for licensing details.

"""Charm the vsz-onboarding-app snap on a machine."""

import logging
import urllib.parse

import ops
from charms.data_platform_libs.v0.data_interfaces import DatabaseRequires

# A standalone module for workload-specific logic (no charming concerns):
import onboarding_app

logger = logging.getLogger(__name__)

DATABASE_NAME = "onboarding"


class OnboardingAppMachineCharm(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.database = DatabaseRequires(self, relation_name="database", database_name=DATABASE_NAME)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.upgrade_charm, self._on_install)
        framework.observe(self.on.start, self._reconcile)
        framework.observe(self.on.update_status, self._reconcile)
        framework.observe(self.database.on.database_created, self._reconcile)
        framework.observe(self.database.on.endpoints_changed, self._reconcile)
        framework.observe(self.on["database"].relation_broken, self._on_database_broken)

    def _on_install(self, event: ops.EventBase):
        """Install the snap attached as the app-snap resource."""
        try:
            snap_path = self.model.resources.fetch("app-snap")
        except (ops.ModelError, NameError):
            self.unit.status = ops.BlockedStatus("attach the app-snap resource")
            return
        self.unit.status = ops.MaintenanceStatus("installing snap")
        onboarding_app.install(snap_path)
        version = onboarding_app.get_version()
        if version is not None:
            self.unit.set_workload_version(version)
        self._reconcile(event)

    def _on_database_broken(self, event: ops.RelationBrokenEvent):
        onboarding_app.unconfigure()
        self.unit.close_port("tcp", onboarding_app.PORT)
        self.unit.status = ops.BlockedStatus("waiting for database relation")

    def _db_uri(self) -> str | None:
        """Build a connection string from the database relation, if it is ready."""
        for data in self.database.fetch_relation_data().values():
            if not all(data.get(key) for key in ("endpoints", "username", "password")):
                continue
            host_port = data["endpoints"].split(",")[0]
            user = urllib.parse.quote(data["username"], safe="")
            password = urllib.parse.quote(data["password"], safe="")
            database = data.get("database", DATABASE_NAME)
            return f"postgresql://{user}:{password}@{host_port}/{database}"
        return None

    def _reconcile(self, event: ops.EventBase):
        """Drive the snap towards the state described by the database relation."""
        if onboarding_app.get_version() is None:
            self.unit.status = ops.BlockedStatus("attach the app-snap resource")
            return
        if not self.model.get_relation("database"):
            self.unit.status = ops.BlockedStatus("waiting for database relation")
            return
        db_uri = self._db_uri()
        if db_uri is None:
            self.unit.status = ops.WaitingStatus("waiting for database credentials")
            return
        self.unit.status = ops.MaintenanceStatus("configuring database")
        onboarding_app.configure(db_uri)
        onboarding_app.migrate()
        self.unit.open_port("tcp", onboarding_app.PORT)
        self.unit.status = ops.ActiveStatus()


if __name__ == "__main__":  # pragma: nocover
    ops.main(OnboardingAppMachineCharm)

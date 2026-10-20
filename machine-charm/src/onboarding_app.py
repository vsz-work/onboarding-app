# Copyright 2026 Vítor Zeni
# See LICENSE file for licensing details.

"""Functions for managing and interacting with the workload.

The workload is the vsz-onboarding-app snap. This module only shells out to snapd,
so it could be used outside the context of a charm.
"""

import logging
import pathlib
import subprocess

logger = logging.getLogger(__name__)

SNAP_NAME = "vsz-onboarding-app"
PORT = 8000


def install(snap_path: pathlib.Path) -> None:
    """Install (or refresh to) a locally built snap file."""
    logger.info("Installing %s from %s", SNAP_NAME, snap_path)
    subprocess.run(["snap", "install", "--dangerous", str(snap_path)], check=True)


def configure(db_uri: str) -> None:
    """Point the snap at the database; its configure hook (re)starts the server."""
    subprocess.run(["snap", "set", SNAP_NAME, f"db-uri={db_uri}"], check=True)


def unconfigure() -> None:
    """Forget the database; the configure hook stops the server."""
    subprocess.run(["snap", "unset", SNAP_NAME, "db-uri"], check=True)


def migrate() -> None:
    """Create the database schema (idempotent)."""
    subprocess.run([f"/snap/bin/{SNAP_NAME}.migrate"], check=True)


def get_version() -> str | None:
    """Get the installed snap version."""
    result = subprocess.run(
        ["snap", "list", SNAP_NAME], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        return None
    # Output: header line, then "<name> <version> <rev> ..."
    lines = result.stdout.splitlines()
    return lines[1].split()[1] if len(lines) > 1 else None

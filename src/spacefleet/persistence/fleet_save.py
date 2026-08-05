"""Fleet spec persistence — plain-JSON save files (stdlib only)."""

from __future__ import annotations

import json
from pathlib import Path

from spacefleet.data.loader import get_data_dir
from spacefleet.models.fleet_spec import (
    FleetSpec,
    FleetSpecError,
    fleet_from_dict,
    fleet_to_dict,
)


def default_fleet_dir() -> Path:
    """``data/fleets`` when the data dir exists, else ``./fleets``."""
    data_dir = get_data_dir()
    base = data_dir if data_dir is not None else Path.cwd()
    return base / "fleets"


def save_fleet(fleet: FleetSpec, path: Path) -> Path:
    """Write *fleet* as pretty JSON, creating parent dirs. Returns *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(fleet_to_dict(fleet), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_fleet(path: Path) -> FleetSpec:
    """Read a fleet JSON file. Raises :class:`FleetSpecError` on any failure."""
    if not path.is_file():
        raise FleetSpecError(f"no such fleet file: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise FleetSpecError(f"{path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise FleetSpecError(f"{path} is not a fleet file (expected a JSON object)")
    return fleet_from_dict(data)

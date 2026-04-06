"""Generic YAML loading utility with graceful fallback.

If PyYAML is not installed, all loading functions return ``None``
and the registries fall back to inline demo data.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── PyYAML availability ──────────────────────────────────────────

try:
    import yaml

    YAML_AVAILABLE = True
except ImportError:
    yaml = None  # type: ignore[assignment]
    YAML_AVAILABLE = False


# ── Data directory discovery ─────────────────────────────────────


def _find_project_root() -> Path | None:
    """Walk up from this file's directory to find ``pyproject.toml``."""
    current = Path(__file__).resolve().parent
    for _ in range(5):
        if (current / "pyproject.toml").is_file():
            return current
        current = current.parent
    return None


def get_data_dir() -> Path | None:
    """Return the path to the ``data/`` directory, or ``None``."""
    env_dir = os.environ.get("SPACEFLEET_DATA_DIR")
    if env_dir:
        p = Path(env_dir)
        if p.is_dir():
            return p
        logger.warning("SPACEFLEET_DATA_DIR=%s does not exist", env_dir)

    root = _find_project_root()
    if root and (root / "data").is_dir():
        return root / "data"
    return None


# ── YAML loading primitives ──────────────────────────────────────


def load_yaml_file(path: Path) -> dict[str, Any] | None:
    """Load a single YAML file.  Returns ``None`` on any failure."""
    if not YAML_AVAILABLE:
        logger.warning("PyYAML not installed — cannot load %s", path)
        return None
    if not path.is_file():
        logger.warning("YAML file not found: %s", path)
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning(
                "Expected mapping in %s, got %s",
                path,
                type(data).__name__,
            )
            return None
        return data
    except yaml.YAMLError as exc:
        logger.warning("Failed to parse %s: %s", path, exc)
        return None


def load_all_yaml_in_dir(
    directory: Path,
    recursive: bool = True,
) -> list[dict[str, Any]]:
    """Load every ``.yaml`` file under *directory*.

    Returns a list of parsed dicts (skipping files that fail).
    """
    results: list[dict[str, Any]] = []
    if not directory.is_dir():
        return results
    pattern = "**/*.yaml" if recursive else "*.yaml"
    for yaml_path in sorted(directory.glob(pattern)):
        data = load_yaml_file(yaml_path)
        if data is not None:
            results.append(data)
    return results

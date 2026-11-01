"""Loading of config.yaml (and experiment overrides)."""

import datetime as dt
import functools
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .schemas.common import Provenance

ROOT = Path(__file__).resolve().parents[2]


def merge_config(base: dict, override: dict) -> dict:
    """Deep-merge ``override`` onto ``base`` (dicts recurse; other values replace)."""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_config(out[key], value)
        else:
            out[key] = value
    return out


def load_config(
    path: str | Path = ROOT / "config.yaml", override: str | Path | None = None
) -> dict:
    """config.yaml, optionally with keys overridden by an experiment config."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if override is not None:
        cfg = merge_config(cfg, yaml.safe_load(Path(override).read_text(encoding="utf-8")))
    return cfg


def config_hash(cfg: dict[str, Any]) -> str:
    # default=str: an unquoted YAML date (transit.date, demand.week) loads as datetime.date
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest()[:16]


def path(cfg: dict, key: str) -> Path:
    """Absolute path of ``paths.<key>``."""
    return ROOT / cfg["paths"][key]


@functools.cache
def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
    except OSError:
        return None
    return out.stdout.strip() or None


def provenance(generator: str, cfg: dict | None = None) -> Provenance:
    """Provenance block for a generated JSON file."""
    return Provenance(
        generated_at=dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        generator=generator,
        config_hash=config_hash(cfg) if cfg is not None else None,
        git_commit=git_commit(),
    )

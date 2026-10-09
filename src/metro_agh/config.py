"""Loading of config.yaml (and experiment overrides)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(
    path: str | Path = ROOT / "config.yaml", override: str | Path | None = None
) -> dict:
    """config.yaml, optionally with keys overridden by an experiment config."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if override is not None:
        cfg = _merge(cfg, yaml.safe_load(Path(override).read_text(encoding="utf-8")))
    return cfg


def config_hash(cfg: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def path(cfg: dict, key: str) -> Path:
    """Absolute path of ``paths.<key>``."""
    return ROOT / cfg["paths"][key]

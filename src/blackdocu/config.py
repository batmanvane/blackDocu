"""Lädt config.yaml aus dem Projektverzeichnis."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_config(path: Path | None = None) -> dict[str, Any]:
    path = path or PROJECT_ROOT / "config.yaml"
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Modellablage setzen, bevor flair/gliner importiert werden (sonst landen sie im Home-Verzeichnis)
    for key, val in (cfg.get("models") or {}).items():
        os.environ.setdefault(key, str(val))
    return cfg


def project_path(rel: str) -> Path:
    return PROJECT_ROOT / rel

"""Load configuration (config.yaml) and secrets (.env)."""
from __future__ import annotations

import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE.parent / ".env")


def load_config(path: str | Path | None = None) -> dict:
    cfg_path = Path(path) if path else HERE / "config.yaml"
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"{cfg_path} not found — copy config.example.yaml to config.yaml"
        )
    with open(cfg_path) as f:
        return yaml.safe_load(f)


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)

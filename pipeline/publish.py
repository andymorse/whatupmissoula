"""Promote a reviewed draft to the live web root.

Review-before-publish: run.py renders into the draft dir; a human checks it;
then this copies the draft into the live output dir that Nginx serves.
"""
from __future__ import annotations

import shutil
from pathlib import Path


def promote(draft_dir: str | Path, live_dir: str | Path) -> Path:
    draft = Path(draft_dir).resolve()
    live = Path(live_dir).resolve()
    if not (draft / "index.html").exists():
        raise FileNotFoundError(f"No rendered draft at {draft} — run the job first.")
    live.mkdir(parents=True, exist_ok=True)
    # Replace live contents with the approved draft.
    for child in live.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in draft.iterdir():
        dest = live / child.name
        if child.is_dir():
            shutil.copytree(child, dest)
        else:
            shutil.copy2(child, dest)
    return live

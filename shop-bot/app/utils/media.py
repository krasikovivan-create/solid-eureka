"""Медиа из папки assets/: значения вида «asset:products/01-0.png»."""

from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile

ASSETS_DIR = Path(__file__).resolve().parents[2] / "assets"
PREFIX = "asset:"


def is_asset(value: str | None) -> bool:
    return bool(value) and value.startswith(PREFIX)


def media_input(value: str) -> str | FSInputFile:
    """URL и file_id отдаются как есть, asset: — как локальный файл."""
    if not is_asset(value):
        return value
    path = (ASSETS_DIR / value.removeprefix(PREFIX)).resolve()
    if ASSETS_DIR.resolve() not in path.parents or not path.is_file():
        raise FileNotFoundError(value)
    return FSInputFile(path)

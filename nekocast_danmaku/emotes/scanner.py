"""Scan <asset_dir>/emotes/ and build an emote name → file path index."""

from __future__ import annotations

from pathlib import Path

from loguru import logger

EMOTE_EXTENSIONS = {".gif", ".png"}


def scan_emotes(asset_dir: Path) -> dict[str, Path]:
    """Return ``{emote_name: <absolute file path>}``."""
    emotes_root = asset_dir / "emotes"
    if not emotes_root.is_dir():
        logger.info("Emotes directory {} does not exist, skipping", emotes_root)
        return {}

    mapping: dict[str, Path] = {}
    for subdir in emotes_root.iterdir():
        if not subdir.is_dir():
            continue
        for file in subdir.iterdir():
            if file.suffix.lower() in EMOTE_EXTENSIONS and file.is_file():
                emote_name = file.stem
                if emote_name in mapping:
                    logger.warning(
                        "Duplicate emote name '{}': {} conflicts with {}",
                        emote_name,
                        file,
                        mapping[emote_name],
                    )
                mapping[emote_name] = file
                logger.debug("Registered emote '{}' -> {}", emote_name, file)

    logger.info("Loaded {} custom emotes from {}", len(mapping), emotes_root)
    return mapping

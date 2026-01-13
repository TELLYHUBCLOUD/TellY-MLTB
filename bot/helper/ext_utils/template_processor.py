import re
from os import path as ospath


def extract_metadata_from_filename(filename: str):
    """
    Extract media information from filename for Auto Thumbnail feature
    Wraps extract_media_info and ensures a dictionary is returned.
    """
    try:
        from bot.helper.mirror_leech_utils.telegram_uploader import (
            extract_media_info,
        )

        name, season, episode, year, part, volume = extract_media_info(filename)

        return {
            "title": name,
            "season": season,
            "episode": episode,
            "year": year,
            "part": part,
            "volume": volume,
        }
    except Exception:
        # Minimal fallback if extract_media_info fails
        name_only = ospath.splitext(filename)[0]
        year_match = re.search(r"\b(19|20)\d{2}\b", name_only)
        year = int(year_match.group(0)) if year_match else None

        return {"title": name_only, "year": year, "season": None, "episode": None}

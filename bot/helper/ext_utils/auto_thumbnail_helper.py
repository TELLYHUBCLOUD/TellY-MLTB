"""
Auto Thumbnail Helper Module
Automatically fetches movie/TV show thumbnails from IMDB and TMDB based on filename metadata
"""

import os
import re
from os import path as ospath

import aiohttp
from aiofiles import open as aioopen

from bot import LOGGER
from bot.core.config_manager import Config
from bot.helper.ext_utils.template_processor import extract_metadata_from_filename


class AutoThumbnailHelper:
    """Helper class for automatically fetching thumbnails from IMDB/TMDB"""

    THUMBNAIL_DIR = "thumbnails/auto"
    CACHE_DURATION = 86400  # 24 hours
    MAX_CACHE_SIZE = 100  # Maximum number of cached thumbnails

    @classmethod
    async def get_auto_thumbnail(
        cls,
        filename: str,
        user_id: int | None = None,
        enabled: bool | None = None,
        thumb_type: str | None = None,
    ) -> str | None:
        """Get auto thumbnail for a file based on its metadata"""
        try:
            auto_enabled = enabled if enabled is not None else Config.AUTO_THUMBNAIL

            if not auto_enabled:
                return None

            metadata = await extract_metadata_from_filename(filename)
            if not metadata:
                return None

            clean_title = cls._extract_clean_title(filename)
            if not clean_title or len(clean_title) < 3:
                return None

            year = metadata.get("year")
            season = metadata.get("season")
            episode = metadata.get("episode")
            is_tv_show = bool(season or episode or cls._detect_tv_patterns(filename))

            cache_key = cls._generate_cache_key(
                clean_title, year, is_tv_show, thumb_type or "poster"
            )
            cached_thumbnail = await cls._get_cached_thumbnail(cache_key)
            if cached_thumbnail:
                return cached_thumbnail

            thumbnail_url = await cls._advanced_search_strategy(
                clean_title, year, is_tv_show, filename, thumb_type
            )

            if not thumbnail_url:
                return None

            return await cls._download_thumbnail(thumbnail_url, cache_key)

        except Exception as e:
            LOGGER.error(f"Error getting auto thumbnail for {filename}: {e}")
            return None

    @classmethod
    def _extract_clean_title(cls, filename: str) -> str:
        # Simplified for brevity, prioritizing the user's logic
        title = filename.rsplit(".", 1)[0] if "." in filename else filename
        title = re.sub(r"[._-]+", " ", title)
        title = re.sub(
            r"\b(720p|1080p|2160p|4k|x264|x265|hevc|bluray|webrip)\b",
            "",
            title,
            flags=re.IGNORECASE,
        )
        # Remove year
        title = re.sub(r"\b(19|20)\d{2}\b", "", title)
        return title.strip()

    @classmethod
    async def _advanced_search_strategy(
        cls, title, year, is_tv, filename, thumb_type=None
    ):
        if Config.TMDB_API_KEY and Config.TMDB_ENABLED:
            res = (
                await TMDBHelper.search_movie_enhanced(title, year)
                if not is_tv
                else await TMDBHelper.search_tv_show_enhanced(title, year)
            )
            if res:
                layout = (thumb_type or Config.AUTO_THUMBNAIL_TYPE).lower()
                path = (
                    res.get("backdrop_path")
                    if layout == "backdrop" and res.get("backdrop_path")
                    else res.get("poster_path")
                )
                if path:
                    return TMDBHelper.get_poster_url(path, "w500")

        if Config.IMDB_ENABLED:
            from bot.modules.imdb import get_poster

            imdb_data = await get_poster(title, False, False)
            if imdb_data and imdb_data.get("poster"):
                return imdb_data["poster"]
        return None

    @classmethod
    def _generate_cache_key(cls, title, year, is_tv, thumb_type):
        return f"{title}_{year}_{'tv' if is_tv else 'movie'}_{thumb_type}".lower().replace(
            " ", "_"
        )

    @classmethod
    async def _get_cached_thumbnail(cls, key):
        path = ospath.join(cls.THUMBNAIL_DIR, f"{key}.jpg")
        if ospath.exists(path):
            return path
        return None

    @classmethod
    async def _download_thumbnail(cls, url, key):
        os.makedirs(cls.THUMBNAIL_DIR, exist_ok=True)
        path = ospath.join(cls.THUMBNAIL_DIR, f"{key}.jpg")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    content = await resp.read()
                    async with aioopen(path, "wb") as f:
                        await f.write(content)
                    return path
        return None

    @classmethod
    def _detect_tv_patterns(cls, filename):
        return bool(
            re.search(
                r"S\d{1,2}E\d{1,3}|Season\s*\d+|Episode\s*\d+|\d{1,2}x\d{1,3}",
                filename,
                re.IGNORECASE,
            )
        )


class TMDBHelper:
    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p"

    @classmethod
    async def search_movie_enhanced(cls, title, year=None):
        return await cls._search("movie", title, year)

    @classmethod
    async def search_tv_show_enhanced(cls, title, year=None):
        return await cls._search("tv", title, year)

    @classmethod
    async def _search(cls, mtype, title, year):
        if not Config.TMDB_API_KEY:
            return None
        params = {
            "api_key": Config.TMDB_API_KEY,
            "query": title,
            "language": Config.TMDB_LANGUAGE,
        }
        if year:
            params["year" if mtype == "movie" else "first_air_date_year"] = year
        async with (
            aiohttp.ClientSession() as session,
            session.get(f"{cls.BASE_URL}/search/{mtype}", params=params) as resp,
        ):
            if resp.status == 200:
                data = await resp.json()
                if data.get("results"):
                    return data["results"][0]
        return None

    @classmethod
    def get_poster_url(cls, path, size="w500"):
        return f"{cls.IMAGE_BASE_URL}/{size}{path}" if path else ""

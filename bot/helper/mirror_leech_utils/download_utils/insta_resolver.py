from typing import ClassVar

from truelink.exceptions import ExtractionFailedException
from truelink.resolvers.base import BaseResolver
from truelink.types import FolderResult, LinkResult

from bot.core.config_manager import Config


class InstagramResolver(BaseResolver):
    """Resolver for Instagram URLs using external InstaDL API"""

    DOMAINS: ClassVar[list[str]] = ["instagram.com", "www.instagram.com"]

    async def resolve(self, url: str) -> LinkResult | FolderResult:
        if not Config.INSTADL_API:
            raise ExtractionFailedException(
                "Instagram downloader API not configured."
            )

        api_url = f"{Config.INSTADL_API}/api/video?postUrl={url}"

        try:
            async with await self._get(api_url) as response:
                if response.status != 200:
                    raise ExtractionFailedException(
                        f"API request failed with status {response.status}"
                    )
                data = await response.json()

            video_url = (
                data.get("data", {}).get("videoUrl")
                if data.get("status") == "success"
                else None
            )

            if not video_url:
                raise ExtractionFailedException(
                    "No video URL found in API response."
                )

            filename, size, mime_type = await self._fetch_file_details(video_url)

            return LinkResult(
                url=video_url,
                filename=filename,
                size=size,
                mime_type=mime_type,
            )

        except Exception as e:
            raise ExtractionFailedException(f"InstagramResolver error: {e}") from e

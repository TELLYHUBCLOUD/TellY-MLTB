from aiohttp import ClientSession
from urllib.parse import quote
from bot import LOGGER
from bot.core.config_manager import Config

__all__ = ["get_terabox_direct_link"]


async def get_terabox_direct_link(terabox_url: str) -> dict:
    try:
        async with ClientSession() as session:
            api_url = f"{Config.TERABOX_API_URL}?url={quote(terabox_url)}"
            LOGGER.info(f"Fetching Terabox link: {api_url}")
            
            async with session.get(api_url, timeout=100) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    if data.get("success"):
                        LOGGER.info(f"Terabox: Got {data.get('file_name')} ({data.get('file_size')})")
                        return {
                            "success": True,
                            "file_name": data.get("file_name", "unknown"),
                            "file_size": data.get("file_size", ""),
                            "size_bytes": data.get("size_bytes", 0),
                            "download_link": data.get("download_link", ""),
                        }
                    else:
                        error_msg = data.get("error", "Unknown error from API")
                        LOGGER.error(f"Terabox API error: {error_msg}")
                        return {
                            "success": False,
                            "error": error_msg
                        }
                else:
                    error_text = await response.text()
                    LOGGER.error(f"Terabox API HTTP {response.status}: {error_text}")
                    return {
                        "success": False,
                        "error": f"API returned status {response.status}"
                    }
                    
    except Exception as e:
        LOGGER.error(f"Terabox API exception: {e}")
        return {
            "success": False,
            "error": str(e)
        }

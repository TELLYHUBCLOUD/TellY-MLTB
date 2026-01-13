import contextlib
import os
from time import time
from urllib.parse import quote

import aiofiles
import aiohttp

from bot import LOGGER

# Supported video formats for LuluStream
VIDEO_FORMATS = (".mp4", ".mkv", ".avi", ".mov", ".flv", ".webm", ".m4v")

# Chunk size for streaming uploads (8MB chunks - balance between memory and upload efficiency)
CHUNK_SIZE = 8 * 1024 * 1024


class AsyncFileReader:
    """
    Async file reader that streams file content in chunks.
    Used for memory-efficient uploads without loading entire file into RAM.
    """

    def __init__(
        self, file_path, file_size, chunk_size=CHUNK_SIZE, progress_callback=None
    ):
        self.file_path = file_path
        self.file_size = file_size
        self.chunk_size = chunk_size
        self.progress_callback = progress_callback
        self.bytes_read = 0
        self._file = None

    async def __aenter__(self):
        self._file = await aiofiles.open(self.file_path, "rb")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._file:
            await self._file.close()

    async def read_chunk(self):
        """Read a single chunk from the file."""
        if self._file is None:
            return b""

        chunk = await self._file.read(self.chunk_size)
        if chunk:
            self.bytes_read += len(chunk)
            if self.progress_callback:
                try:
                    self.progress_callback(self.bytes_read)
                except Exception:
                    pass  # Ignore progress callback errors
        return chunk


async def async_file_generator(
    file_path, file_size, chunk_size=CHUNK_SIZE, progress_callback=None
):
    """
    Async generator that yields file chunks for streaming upload.
    Memory efficient - only one chunk in memory at a time.
    """
    bytes_read = 0
    async with aiofiles.open(file_path, "rb") as f:
        while True:
            chunk = await f.read(chunk_size)
            if not chunk:
                break
            bytes_read += len(chunk)
            if progress_callback:
                with contextlib.suppress(Exception):
                    progress_callback(bytes_read)
            yield chunk


class LuluStream:
    def __init__(self, listener, path, api_key):
        self.listener = listener
        self._path = path
        self.api_key = api_key.strip()
        self.base_url = "https://lulustream.com/api/"
        self.tool = "LuluStream"
        self.__processed_bytes = 0
        self.last_uploaded = 0
        self.start_time = time()
        self._updater = None
        self.update_interval = 3

    @property
    def speed(self):
        try:
            return self.__processed_bytes / (time() - self.start_time)
        except ZeroDivisionError:
            return 0

    @property
    def processed_bytes(self):
        return self.__processed_bytes

    def __progress_callback(self, current):
        self.__processed_bytes = current

    async def get_upload_server(self):
        encoded_key = quote(self.api_key, safe="")
        url = f"{self.base_url}upload/server?key={encoded_key}"
        try:
            async with aiohttp.ClientSession() as session:
                headers = {"User-Agent": "Mozilla/5.0"}
                async with session.get(url, headers=headers, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == 200:
                            return data.get("result")
        except Exception as e:
            LOGGER.error(f"LuluStream Request Exception: {e}")
        return None

    async def upload(self):
        server_url = await self.get_upload_server()
        if not server_url:
            await self.listener.on_upload_error(
                "Failed to get LuluStream upload server."
            )
            return

        filename = os.path.basename(self._path)
        try:
            file_size = os.path.getsize(self._path)
            LOGGER.info(f"LuluStream Upload Starting: {filename}")

            # Using custom generator for progress tracking
            async def progress_generator():
                async for chunk in async_file_generator(
                    self._path, file_size, progress_callback=self.__progress_callback
                ):
                    yield chunk

            data = aiohttp.FormData()
            data.add_field("key", self.api_key)
            data.add_field("file_title", filename)
            data.add_field(
                "file",
                progress_generator(),
                filename=filename,
                content_type="application/octet-stream",
            )

            timeout = aiohttp.ClientTimeout(total=7200)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(server_url, data=data) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get("status") == 200:
                            files = result.get("files", [])
                            if files:
                                file_code = files[0].get("filecode")
                                link = f"https://lulustream.com/{file_code}"
                                await self.listener.on_upload_complete(
                                    link, 1, 0, "File", ""
                                )
                                return
                        await self.listener.on_upload_error(
                            f"LuluStream Error: {result.get('msg')}"
                        )
                    else:
                        await self.listener.on_upload_error(
                            f"LuluStream HTTP Error: {resp.status}"
                        )
        except Exception as e:
            await self.listener.on_upload_error(f"LuluStream Exception: {e}")

    async def cancel_task(self):
        self.listener.is_cancelled = True

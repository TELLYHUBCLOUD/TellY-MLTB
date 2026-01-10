from logging import getLogger
from os import path as ospath

from aiofiles.os import makedirs

from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


class GoogleDriveDownload(GoogleDriveHelper):
    def __init__(self, listener, path):
        self.listener = listener
        self._path = path
        self._is_cancelled = False
        super().__init__()

    async def download(self):
        try:
            file_id = self.get_id_from_url(self.listener.link)
        except (KeyError, IndexError):
            file_id = self.listener.link

        try:
            file = self.get_file_metadata(file_id)
        except Exception as e:
            await self.listener.on_download_error(str(e))
            return

        if file is None:
            await self.listener.on_download_error("File not found!")
            return

        self.listener.name = (
            self.listener.name
            or file.get("name")
            or "Unknown"
        )

        if file.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
            self.listener.is_file = False
            self.listener.name = self.listener.name.replace("/", "_")
            path = ospath.join(self._path, self.listener.name)
            await makedirs(path, exist_ok=True)
            await sync_to_async(
                self._download_folder,
                file_id,
                path,
                self.listener.name,
            )
        else:
            self.listener.is_file = True
            await sync_to_async(
                self._download_file,
                file_id,
                self._path,
                self.listener.name,
                file.get("mimeType"),
            )

        if self._is_cancelled:
            return

        await self.listener.on_download_complete()

    def _download_folder(self, folder_id, path, folder_name):
        if self._is_cancelled:
            return
        files = self.get_files_by_folder_id(folder_id)
        if len(files) == 0:
            return

        for item in files:
            if self._is_cancelled:
                break
            file_id = item.get("id")
            filename = item.get("name")
            mime_type = item.get("mimeType")
            if item.get("mimeType") == "application/vnd.google-apps.shortcut":
                file_id = item.get("shortcutDetails").get("targetId")
                mime_type = item.get("shortcutDetails").get("targetMimeType")

            if mime_type == self.G_DRIVE_DIR_MIME_TYPE:
                new_path = ospath.join(path, filename)
                if not ospath.exists(new_path):
                    makedirs(new_path, exist_ok=True)
                self._download_folder(file_id, new_path, filename)
            elif (
                ospath.isfile(f"{path}{filename}")
                or (
                    self.listener.included_extensions
                    and not filename.strip()
                    .lower()
                    .endswith(tuple(self.listener.included_extensions))
                )
                or (
                    not self.listener.included_extensions
                    and filename.strip()
                    .lower()
                    .endswith(tuple(self.listener.excluded_extensions))
                )
            ):
                continue
            else:
                self._download_file(file_id, path, filename, mime_type)

    def _download_file(self, file_id, path, filename, mime_type):
        if self._is_cancelled:
            return
        try:
            self.download_file(file_id, path, filename, mime_type)
        except Exception as e:
            LOGGER.error(f"Download Error: {e}")

    async def cancel_task(self):
        self._is_cancelled = True
        LOGGER.info(f"Cancelling Download: {self.listener.name}")

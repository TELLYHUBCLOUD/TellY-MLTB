from logging import getLogger
from os import path as ospath

from aiofiles.os import makedirs

from bot.helper.ext_utils.bot_utils import sync_to_async
from bot.helper.mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


class GoogleDriveClone(GoogleDriveHelper):
    def __init__(self, listener):
        self.listener = listener
        self.proc_bytes = 0
        self.failed = 0
        self.total_files = 0
        self.status = "cl"
        self._is_cancelled = False
        super().__init__()

    async def clone(self):
        try:
            file_id = self.get_id_from_url(self.listener.link)
        except (KeyError, IndexError):
            file_id = self.listener.link
        msg = ""
        LOGGER.info(f"File ID: {file_id}")
        try:
            file = self.get_file_metadata(file_id)
        except Exception as e:
            LOGGER.error(f"Clone Error: {e}")
            await self.listener.on_upload_error(str(e))
            return
        if file is None:
            await self.listener.on_upload_error("File not found!")
            return

        self.listener.name = (
            self.listener.name
            or file.get("name")
            or "Unknown"
        )

        if self.listener.up_dest.startswith("mtp:"):
            self.listener.up_dest = self.listener.up_dest.replace("mtp:", "", 1)

        try:
            if file.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                await self._clone_folder(self.listener.name, file_id, self.listener.up_dest)
            else:
                if (
                    self.listener.included_extensions
                    and not self.listener.name.strip().lower().endswith(tuple(self.listener.included_extensions))
                ) or (
                    not self.listener.included_extensions
                    and self.listener.name.strip().lower().endswith(tuple(self.listener.excluded_extensions))
                ):
                    await self.listener.on_upload_error("File excluded!")
                    return
                self.total_files += 1
                self._copy_file(file_id, self.listener.up_dest)
                self.proc_bytes += int(file.get("size", 0))
        except Exception as e:
            LOGGER.error(f"Clone Error: {e}")
            if isinstance(e, RetryError):
                LOGGER.info(f"Total Attempts: {e.last_attempt.attempt_number}")
                err = e.last_attempt.exception()
                LOGGER.error(f"{err}")
            await self.listener.on_upload_error(str(e))
            return

        if self._is_cancelled:
            return

        LOGGER.info(f"Clone Done: {self.listener.name}")
        await self.listener.on_upload_complete(
            None,
            None,
            self.total_files,
            0,
            None,
            None,
        )

    def _clone_folder(self, folder_name, folder_id, dest_id):
        if self._is_cancelled:
            return
        files = self.get_files_by_folder_id(folder_id)
        if len(files) == 0:
            return
        current_dir_id = self.create_directory(folder_name, dest_id)
        for file in files:
            if self._is_cancelled:
                break
            file_path = ospath.join(folder_name, file.get("name"))
            if file.get("mimeType") == self.G_DRIVE_DIR_MIME_TYPE:
                self._clone_folder(file.get("name"), file.get("id"), current_dir_id)
            elif (
                self.listener.included_extensions
                and not file.get("name")
                .strip()
                .lower()
                .endswith(tuple(self.listener.included_extensions))
            ) or (
                not self.listener.included_extensions
                and file.get("name")
                .strip()
                .lower()
                .endswith(tuple(self.listener.excluded_extensions))
            ):
                continue
            else:
                self.total_files += 1
                self._copy_file(file.get("id"), current_dir_id)
                self.proc_bytes += int(file.get("size", 0))

    def _copy_file(self, file_id, dest_id):
        if self._is_cancelled:
            return
        try:
            self.copy_file(file_id, dest_id)
        except Exception as e:
            LOGGER.error(f"Copy Error: {e}")
            self.failed += 1

    @property
    def speed(self):
        return self.proc_bytes / (time() - self.listener.start_time)

    @property
    def processed_bytes(self):
        return self.proc_bytes

    async def cancel_task(self):
        self._is_cancelled = True
        LOGGER.info(f"Cancelling Clone: {self.listener.name}")
        await self.listener.on_upload_error("Your Clone has been stopped!")

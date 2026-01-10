from logging import getLogger
from os import path as ospath

from aiofiles.os import listdir
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot import intervals
from bot.helper.ext_utils.files_utils import get_mime_type
from bot.helper.mirror_leech_utils.gdrive_utils.helper import GoogleDriveHelper

LOGGER = getLogger(__name__)


class GoogleDriveUpload(GoogleDriveHelper):
    def __init__(self, listener, path):
        self.listener = listener
        self._path = path
        self.proc_bytes = 0
        self.failed = 0
        self.total_files = 0
        self.status = "up"
        self._is_cancelled = False
        super().__init__()

    async def upload(self):
        self.listener.up_dest = self.listener.up_dest.replace("mtp:", "", 1)
        self.listener.up_dest = self.listener.up_dest.replace("tp:", "", 1)
        self.listener.up_dest = self.listener.up_dest.replace("sa:", "", 1)

        if self.listener.up_dest == "root":
            self.listener.up_dest = "root"

        self.total_files = 0
        self.failed = 0
        self.proc_bytes = 0

        try:
            if ospath.isfile(self._path):
                self.total_files += 1
                mime_type = get_mime_type(self._path)
                self._upload_file(self._path, self.listener.up_dest, mime_type)
            else:
                self._upload_dir(self._path, self.listener.up_dest)
        except Exception as e:
            LOGGER.error(f"Upload Error: {e}")
            if isinstance(e, RetryError):
                LOGGER.info(f"Total Attempts: {e.last_attempt.attempt_number}")
                err = e.last_attempt.exception()
                LOGGER.error(f"{err}")
            await self.listener.on_upload_error(str(e))
            return

        if self._is_cancelled:
            return

        if self.failed == self.total_files:
            await self.listener.on_upload_error("All files failed to upload!")
            return

        LOGGER.info(f"Upload Done: {self.listener.name}")
        await self.listener.on_upload_complete(
            None,
            None,
            self.total_files,
            self.failed,
            None,
            None,
        )

    def _upload_dir(self, input_directory, dest_id):
        if self._is_cancelled:
            return None
        list_dirs = listdir(input_directory)
        if len(list_dirs) == 0:
            return None
        new_id = None
        for item in list_dirs:
            current_file_name = ospath.join(input_directory, item)
            if not ospath.exists(current_file_name):
                if intervals["stopAll"]:
                    return None
                LOGGER.error(f"{current_file_name} not exists! Continue uploading!")
                continue
            if ospath.isdir(current_file_name):
                current_dir_id = self.create_directory(item, dest_id)
                new_id = self._upload_dir(
                    current_file_name,
                    current_dir_id,
                )
            else:
                self.total_files += 1
                mime_type = get_mime_type(current_file_name)
                self._upload_file(current_file_name, dest_id, mime_type)
        return new_id

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    def _upload_file(self, file_path, dest_id, mime_type):
        if self._is_cancelled:
            return
        try:
            self.upload_file(file_path, dest_id, mime_type)
            self.proc_bytes += ospath.getsize(file_path)
        except Exception as e:
            LOGGER.error(f"Upload Error: {e}")
            self.failed += 1
            raise e

    @property
    def speed(self):
        return self.proc_bytes / (time() - self.listener.start_time)

    @property
    def processed_bytes(self):
        return self.proc_bytes

    async def cancel_task(self):
        self._is_cancelled = True
        LOGGER.info(f"Cancelling Upload: {self.listener.name}")
        await self.listener.on_upload_error("Your Upload has been stopped!")

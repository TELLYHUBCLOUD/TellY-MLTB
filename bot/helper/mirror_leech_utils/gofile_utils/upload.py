from json import JSONDecodeError
from logging import getLogger
from os import path as ospath

from aiofiles.os import listdir
from aiohttp import ClientSession, ContentTypeError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bot import user_data
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import SetInterval

LOGGER = getLogger(__name__)


class GoFileUpload:
    def __init__(self, listener, path):
        self.listener = listener
        self._path = path
        self.proc_bytes = 0
        self.failed = 0
        self.total_files = 0
        self.status = "up"
        self._is_cancelled = False
        self._is_errored = False
        self.api_url = "https://api.gofile.io/"
        self.token = None
        self.folder_id = None
        self.update_interval = 3

        # Get user-specific token or fall back to global config
        user_dict = user_data.get(self.listener.user_id, {})
        self.token = user_dict.get("GOFILE_TOKEN") or Config.GOFILE_API
        self.folder_id = (
            user_dict.get("GOFILE_FOLDER_ID") or Config.GOFILE_FOLDER_ID or None
        )

    def __progress_callback(self, current, total):
        self.proc_bytes += current

    async def __resp_handler(self, response):
        if response["status"] == "ok":
            return response["data"]
        raise Exception(f"GoFile API Error: {response['status']}")

    async def __getServer(self):
        async with (
            ClientSession() as session,
            session.get(f"{self.api_url}servers") as resp,
        ):
            return await self.__resp_handler(await resp.json())

    async def __getAccount(self, check_account=False):
        if self.token is None:
            return None
        async with (
            ClientSession() as session,
            session.get(f"{self.api_url}accounts/get?token={self.token}") as resp,
        ):
            try:
                res = await resp.json()
            except Exception:
                return None
            if res["status"] != "ok":
                return None
            if check_account:
                return res["data"]
            return res["data"]["rootFolder"]

    @retry(
        wait=wait_exponential(multiplier=2, min=4, max=8),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
    )
    async def upload_aiohttp(self, url, file_path, req_file, data):
        if self._is_cancelled:
            return None
        import aiohttp

        data["token"] = self.token
        if self.folder_id:
            data["folderId"] = self.folder_id

        async with aiohttp.MultipartWriter("form-data") as mp:
            for key, value in data.items():
                part = mp.append(str(value))
                part.set_content_disposition("form-data", name=key)

            part = mp.append(open(file_path, "rb"))
            part.set_content_disposition(
                "form-data", name=req_file, filename=ospath.basename(file_path)
            )

            async with (
                ClientSession() as session,
                session.post(url, data=mp) as resp,
            ):
                if resp.status == 200:
                    try:
                        return await resp.json()
                    except ContentTypeError:
                        return {
                            "status": "ok",
                            "data": {"downloadPage": "Uploaded"},
                        }
                    except JSONDecodeError:
                        return {
                            "status": "ok",
                            "data": {"downloadPage": "Uploaded"},
                        }
                else:
                    raise Exception(f"HTTP {resp.status}: {await resp.text()}")
        return None

    async def create_folder(self, parentFolderId, folderName):
        if self._is_cancelled:
            return None
        async with ClientSession() as session:
            data = {
                "token": self.token,
                "parentFolderId": parentFolderId,
                "folderName": folderName,
            }
            async with session.put(
                f"{self.api_url}contents/createFolder", data=data
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def set_folder_option(self, folderId, option, value):
        if self._is_cancelled:
            return None
        async with ClientSession() as session:
            data = {
                "token": self.token,
                "folderId": folderId,
                "option": option,
                "value": value,
            }
            async with session.put(
                f"{self.api_url}contents/setOption", data=data
            ) as resp:
                return await self.__resp_handler(await resp.json())

    async def upload(self):
        if not self.token:
            await self.listener.on_upload_error("GoFile Token not found!")
            return

        if not self.folder_id:
            self.folder_id = await self.__getAccount()
            if self.folder_id is None:
                await self.listener.on_upload_error("GoFile Token is invalid!")
                return

        try:
            server = await self.__getServer()
            self.server = server["server"]
        except Exception as e:
            await self.listener.on_upload_error(str(e))
            return

        self.updater = SetInterval(self.update_interval, self._update_stats)
        try:
            if ospath.isfile(self._path):
                self.total_files += 1
                await self._upload_file(self._path)
            else:
                await self._upload_dir(self._path, self.folder_id)
        except Exception as e:
            LOGGER.error(f"Upload Error: {e}")
            if isinstance(e, RetryError):
                LOGGER.info(f"Total Attempts: {e.last_attempt.attempt_number}")
                err = e.last_attempt.exception()
                LOGGER.error(f"{err}")
            await self.listener.on_upload_error(str(e))
            return
        finally:
            self.updater.cancel()

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

    async def _upload_dir(self, input_directory, dest_id):
        if self._is_cancelled:
            return
        list_dirs = await listdir(input_directory)
        if len(list_dirs) == 0:
            return
        for item in list_dirs:
            current_file_name = ospath.join(input_directory, item)
            if ospath.isdir(current_file_name):
                folder = await self.create_folder(dest_id, item)
                await self._upload_dir(current_file_name, folder["id"])
            else:
                self.total_files += 1
                self.folder_id = dest_id
                await self._upload_file(current_file_name)

    async def _upload_file(self, file_path):
        if self._is_cancelled:
            return
        try:
            url = f"https://{self.server}.gofile.io/contents/uploadfile"
            req_file = "file"
            data = {}
            await self.upload_aiohttp(url, file_path, req_file, data)
        except Exception as e:
            LOGGER.error(f"Upload Error: {e}")
            self.failed += 1
            raise e

    async def _update_stats(self):
        # Implementation for update stats
        pass

    async def is_goapi(self, token):
        if not token:
            return False
        try:
            async with (
                ClientSession() as session,
                session.get(f"{self.api_url}accounts/get?token={token}") as resp,
            ):
                res = await resp.json()
                if res["status"] == "ok":
                    return True
        except Exception:
            return False
        return False

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

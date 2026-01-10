import contextlib
from asyncio import create_subprocess_exec, gather, wait_for
from asyncio.subprocess import PIPE
from configparser import RawConfigParser
from json import loads
from logging import getLogger
from os import path as ospath
from random import randrange
from re import findall
from time import time

from aiofiles.os import path as aiopath

from bot import LOGGER, task_dict_lock
from bot.core.config_manager import Config
from bot.helper.ext_utils.bot_utils import cmd_exec, new_task
from bot.helper.ext_utils.files_utils import count_files_and_folders, get_mime_type
from bot.helper.ext_utils.status_utils import get_readable_file_size

LOGGER = getLogger(__name__)


class RcloneTransferHelper:
    def __init__(self, listener):
        self.listener = listener
        self._proc_bytes = 0
        self._failed = 0
        self._total_files = 0
        self._transferred_size = "0 B"
        self._status = "up"
        self._is_cancelled = False
        self._is_errored = False
        self._sa_index = 0
        self._sa_number = 0
        self._use_service_accounts = Config.USE_SERVICE_ACCOUNTS

    @property
    def transferred_size(self):
        return self._transferred_size

    @property
    def percentage(self):
        return self._percentage

    @property
    def speed(self):
        return self._speed

    @property
    def eta(self):
        return self._eta

    async def _progress(self):
        while not self._is_cancelled and not self._is_errored:
            try:
                data = await self.get_rclone_data()
                if not data:
                    continue
            except Exception:
                continue
            if data:
                (
                    self._percentage,
                    self._transferred_size,
                    self._speed,
                    self._eta,
                ) = data[0]

    def _switch_service_account(self):
        if self._sa_index == self._sa_number - 1:
            self._sa_index = 0
        else:
            self._sa_index += 1

    async def get_rclone_data(self):
        # Implementation to parse rclone progress output
        pass

    async def upload(self, path):
        if self._is_cancelled:
            return

        cmd = self._get_updated_command(path, self.listener.up_dest, "copy")
        if self._use_service_accounts:
            # Add service account logic here
            pass

        self._proc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._progress()
        returncode = await self._proc.wait()

        if returncode == 0:
            LOGGER.info(f"Rclone Upload Done: {self.listener.name}")
            await self.listener.on_upload_complete(
                None,
                None,
                self._total_files,
                0,
                None,
                None,
            )
        else:
            LOGGER.error(f"Rclone Upload Failed: {self.listener.name}")
            await self.listener.on_upload_error("Rclone Upload Failed!")

    def _get_updated_command(
        self,
        source,
        destination,
        method,
    ):
        rclone_select = False
        if source.split(":")[-1].startswith("rclone_select"):
            source = f"{source.split(':')[0]}:"
            rclone_select = True
        cmd = [
            "xone",
            method,
            source,
            destination,
            "--stats",
            "1s",
            "--progress",
            "--drive-chunk-size",
            "64M",
            "--transfers",
            "4",
            "--checkers",
            "4",
            "--log-level",
            "NOTICE",
            "--user-agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36",
            "-v",
            "--retries",
            "1",
            "-M",
        ]
        if rclone_select:
            cmd.extend(("--files-from", self.listener.link))
        elif self.listener.included_extensions:
            ext = "*.{" + ",".join(self.listener.included_extensions) + "}"
            cmd.extend(("--include", ext))
        else:
            ext = "*.{" + ",".join(self.listener.excluded_extensions) + "}"
            cmd.extend(("--exclude", ext))
        if rcflags := self.listener.rc_flags:
            rcflags = rcflags.split("|")
            for flag in rcflags:
                if ":" in flag:
                    key, value = flag.split(":")
                    cmd.extend((key, value))
                elif len(flag) > 0:
                    cmd.append(flag)
        return cmd

    async def cancel_task(self):
        self._is_cancelled = True
        if self._proc:
            try:
                self._proc.kill()
            except Exception:
                pass
        LOGGER.info(f"Cancelling Rclone Upload: {self.listener.name}")
        await self.listener.on_upload_error("Your Rclone Upload has been stopped!")

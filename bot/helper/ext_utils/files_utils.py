from asyncio import create_subprocess_exec, wait_for
from asyncio.subprocess import PIPE
from os import path as ospath
from os import readlink, walk
from re import search as re_search

from aiofiles.os import makedirs, remove
from aioshutil import move

from bot import LOGGER
from bot.helper.ext_utils.bot_utils import sync_to_async

from .exceptions import NotSupportedExtractor


class SevenZ:
    def __init__(self, listener):
        self._listener = listener
        self._processed_bytes = 0
        self._percentage = "0%"

    @property
    def processed_bytes(self):
        return self._processed_bytes

    @property
    def progress(self):
        return self._percentage

    async def _sevenz_progress(self):
        pattern = r"(\d+)\s+bytes|Total Physical Size\s*=\s*(\d+)|Physical Size\s*=\s*(\d+)"
        while not (
            self._listener.subproc.returncode is not None
            or self._listener.is_cancelled
        ):
            try:
                line = await wait_for(self._listener.subproc.stdout.readline(), 5)
            except Exception:
                break
            line = line.decode().strip()
            if "%" in line:
                perc = line.split("%", 1)[0]
                if perc.isdigit():
                    self._percentage = f"{perc}%"
                    self._processed_bytes = (
                        int(perc) / 100
                    ) * self._listener.subsize
                else:
                    self._percentage = "0%"
                continue
            if match := re_search(pattern, line):
                self._listener.subsize = int(match[1] or match[2] or match[3])
        s = b""
        while not (
            self._listener.is_cancelled
            and self._listener.subproc.returncode is not None
        ):
            try:
                chunk = await wait_for(self._listener.subproc.stdout.read(1), 5)
            except Exception:
                break
            if not chunk:
                break
            s += chunk
            if s.endswith(b"\n"):
                line = s.decode().strip()
                if "%" in line:
                    perc = line.split("%", 1)[0]
                    if perc.isdigit():
                        self._percentage = f"{perc}%"
                        self._processed_bytes = (
                            int(perc) / 100
                        ) * self._listener.subsize
                    else:
                        self._percentage = "0%"
                if match := re_search(pattern, line):
                    self._listener.subsize = int(match[1] or match[2] or match[3])
                    self._processed_bytes = 0
                    self._percentage = "0%"
                s = b""

        self._processed_bytes = 0
        self._percentage = "0%"

    async def extract(self, path, extract_path, password):
        self._listener.subsize = await get_path_size(path)
        cmd = [
            "7z",
            "x",
            f"-p{password}",
            path,
            f"-o{extract_path}",
            "-aot",
            "-xr!@PaxHeader",
            "-bso1",
            "-bsp1",
        ]
        if not password:
            del cmd[2]
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._sevenz_progress()
        return await self._listener.subproc.wait()

    async def zip(self, path, zip_path, password):
        self._listener.subsize = await get_path_size(path)
        if ospath.isdir(path):
            path = ospath.join(path, "*")
        cmd = [
            "7z",
            "a",
            f"-p{password}",
            zip_path,
            path,
            "-mx=0",
            "-bso1",
            "-bsp1",
        ]
        if not password:
            del cmd[2]
        self._listener.subproc = await create_subprocess_exec(
            *cmd,
            stdout=PIPE,
            stderr=PIPE,
        )
        await self._sevenz_progress()
        return await self._listener.subproc.wait()


async def get_path_size(path):
    if await aiopath.isfile(path):
        return await aiopath.getsize(path)
    total_size = 0
    for root, _, files in await sync_to_async(walk, path):
        for f in files:
            fp = ospath.join(root, f)
            total_size += await aiopath.getsize(fp)
    return total_size


async def count_files_and_folders(path, extension_filter=None):
    total_files = 0
    total_folders = 0
    for _, dirs, files in await sync_to_async(walk, path):
        total_folders += len(dirs)
        if extension_filter:
            total_files += len(
                [f for f in files if f.lower().endswith(tuple(extension_filter))]
            )
        else:
            total_files += len(files)
    return total_files, total_folders


def get_base_name(orig_path):
    extension = next(
        (ext for ext in [".rar", ".tar", ".zip", ".7z"] if orig_path.endswith(ext)),
        "",
    )
    if not extension:
        raise NotSupportedExtractor
    name = orig_path.rsplit(extension, 1)[0]
    return name


def get_mime_type(file_path: str) -> str:
    from magic import Magic

    mime = Magic(mime=True)
    return mime.from_file(file_path)


async def remove_excluded_files(fpath, ee):
    for root, _, files in await sync_to_async(walk, fpath):
        if root.strip().endswith("/yt-dlp-thumb"):
            continue
        for f in files:
            if f.strip().lower().endswith(tuple(ee)):
                await remove(ospath.join(root, f))


async def remove_non_included_files(fpath, ie):
    for root, _, files in await sync_to_async(walk, fpath):
        if root.strip().endswith("/yt-dlp-thumb"):
            continue
        for f in files:
            if f.strip().lower().endswith(tuple(ie)):
                continue
            await remove(ospath.join(root, f))


async def join_files(opath):
    files = await listdir(opath)
    results = []
    for file_ in files:
        if re_search(r"\.0+2$", file_) and await aiopath.isfile(
            f"{opath}/{file_}",
        ):
            results.append(file_)
    if not results:
        return
    LOGGER.info("Joining Files ...")
    for res in results:
        base_name = res.rsplit(".", 1)[0]
        cmd = [
            "7z",
            "x",
            f"{opath}/{base_name}.*",
            f"-o{opath}",
            "-aot",
            "-xr!@PaxHeader",
        ]
        process = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
        await process.wait()
        if process.returncode != 0:
            LOGGER.error(f"Error joining files: {base_name}")
            continue
        for file_ in files:
            if file_.startswith(base_name) and await aiopath.isfile(
                f"{opath}/{file_}",
            ):
                await remove(f"{opath}/{file_}")


async def split_file(path, split_size, listener):
    parts = -(-await get_path_size(path) // split_size)
    if parts <= 1:
        return False
    if listener.is_cancelled:
        return False
    listener.subsize = await get_path_size(path)
    cmd = [
        "7z",
        "a",
        f"-v{split_size}b",
        f"{path}.7z",
        path,
        "-mx=0",
        "-bso1",
        "-bsp1",
    ]
    listener.subproc = await create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
    await SevenZ(listener)._sevenz_progress()
    return await listener.subproc.wait() == 0


def is_archive(file_path):
    return file_path.endswith((".zip", ".rar", ".tar", ".7z", ".gz", ".bz2", ".xz", ".iso"))


def is_archive_split(file_path):
    return re_search(r"\.r\d+$|\.\d+$|\.part\d+\.rar$|\.z\d+$", file_path)


def is_first_archive_split(file_path):
    return re_search(r"\.r0+1$|\.0+1$|\.part0*1\.rar$|\.z0+1$", file_path)

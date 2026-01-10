from bot import sabnzbd_client
from bot.helper.ext_utils.status_utils import (
    MirrorStatus,
    get_readable_file_size,
    get_readable_time,
    time_to_seconds,
)


async def get_download(nzo_id, old_info=None):
    if old_info is None:
        old_info = {}
    try:
        queue = await sabnzbd_client.get_downloads(nzo_ids=nzo_id)
        if res := queue["queue"]["slots"]:
            return res[0]
        history = await sabnzbd_client.get_history(nzo_ids=nzo_id)
        if res := history["history"]["slots"]:
            return res[0]
    except Exception:
        pass
    return old_info


class SabnzbdStatus:
    def __init__(self, listener, gid, queued=False):
        self.queued = queued
        self.listener = listener
        self._gid = gid
        self._info = {}
        self.tool = "sabnzbd"

    async def update(self):
        self._info = await get_download(self._gid, self._info)

    def progress(self):
        return f"{self._info.get('percentage', '0')}%"

    def processed_raw(self):
        return (
            float(self._info.get("mb", "0")) - float(self._info.get("mbleft", "0"))
        ) * 1048576

    def processed_bytes(self):
        return get_readable_file_size(self.processed_raw())

    def speed_raw(self):
        if self._info.get("mb", "0") == self._info.get("mbleft", "0"):
            return 0
        try:
            return (
                int(float(self._info.get("mbleft", "0")) * 1048576) / self.eta_raw()
            )
        except Exception:
            return 0

    def speed(self):
        return f"{get_readable_file_size(self.speed_raw())}/s"

    def name(self):
        return self._info.get("filename", "")

    def size(self):
        return self._info.get("size", 0)

    def eta_raw(self):
        return int(time_to_seconds(self._info.get("timeleft", "0")))

    def eta(self):
        return get_readable_time(self.eta_raw())

    async def status(self):
        await self.update()
        if self._info.get("mb", "0") == self._info.get("mbleft", "0"):
            return MirrorStatus.STATUS_QUEUEDL
        state = self._info.get("status")
        if state == "Paused" and self.queued:
            return MirrorStatus.STATUS_QUEUEDL
        if state in [
            "QuickCheck",
            "Verifying",
            "Repairing",
            "Fetching",
            "Moving",
            "Extracting",
        ]:
            return MirrorStatus.STATUS_DOWNLOAD
        return MirrorStatus.STATUS_DOWNLOAD

    def task(self):
        return self

    async def cancel_task(self):
        self.listener.is_cancelled = True
        await sabnzbd_client.delete_job(self._gid, delete_files=True)

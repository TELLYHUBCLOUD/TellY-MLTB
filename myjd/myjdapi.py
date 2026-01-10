"""
myjdapi
~~~~~~~

:author:     Rudolf
:copyright:  Copyright 2016 Rudolf
:license:    GPLv3, see LICENSE for details.
:version:    1.1.7
"""

import time


def chunks(l, n):
    """Yield successive n-sized chunks from l."""
    for i in range(0, len(l), n):
        yield l[i : i + n]


def get_commands():
    """Reads the command list file."""
    # Placeholder for getting commands
    return {}


class TokenExpiredException(Exception):
    pass


class Jddevice:
    def __init__(self, jd):
        """This functions initializes the device instance.
        It uses the provided dictionary to create the device.

        :param device_dict: Device dictionary
        """
        self.jd = jd
        self.name = jd.device_name
        self.device_id = jd.device_id
        self.linkgrabber = Linkgrabber(self)
        self.downloads = Downloads(self)
        self.captcha = Captcha(self)

    async def stop(self):
        """Stops JDownloader."""
        return await self.jd.action("/system/shutdown", [])

    async def start(self):
        """Starts JDownloader."""
        return await self.jd.action("/system/restart", [])


class Linkgrabber:
    def __init__(self, device):
        self.device = device

    async def add_links(self, params):
        return await self.device.jd.action("/linkgrabberv2/addLinks", params)

    async def is_collecting(self):
        return await self.device.jd.action("/linkgrabberv2/isCollecting", [])

    async def clear_list(self):
        return await self.device.jd.action("/linkgrabberv2/clearList", [])

    async def query_packages(self, params):
        return await self.device.jd.action("/linkgrabberv2/queryPackages", params)

    async def move_to_downloadlist(self, link_ids, package_ids):
        return await self.device.jd.action(
            "/linkgrabberv2/moveToDownloadlist", [link_ids, package_ids]
        )


class Downloads:
    def __init__(self, device):
        self.device = device

    async def query_links(self):
        return await self.device.jd.action("/downloads/queryLinks", [])

    async def query_packages(self):
        return await self.device.jd.action("/downloads/queryPackages", [])

    async def remove_links(self, link_ids=None, package_ids=None):
        if link_ids is None:
            link_ids = []
        if package_ids is None:
            package_ids = []
        return await self.device.jd.action(
            "/downloads/removeLinks", [link_ids, package_ids]
        )


class Captcha:
    def __init__(self, device):
        self.device = device

    async def list(self):
        return await self.device.jd.action("/captcha/list", [])

    async def solve(self, captcha_id, solution):
        return await self.device.jd.action("/captcha/solve", [captcha_id, solution])


class MyJdApi:
    def __init__(self):
        self.app_key = "http://git.io/v3F9t"
        self.api_url = "https://api.jdownloader.org"
        self.rid = int(time.time())
        self.device = None

    async def connect(self, email, password):
        # Placeholder connect logic
        pass

    async def get_device(self, device_name):
        # Placeholder get_device logic
        pass

    async def action(self, path, params):
        # Placeholder action logic
        pass

from logging import (
    FileHandler,
    Formatter,
    LogRecord,
    StreamHandler,
    basicConfig,
    getLogger,
)
from os import makedirs, path, cpu_count
from socket import gethostname

from dotenv import load_dotenv
from uvloop import install

install()

# Setup logging
makedirs("log", exist_ok=True)
load_dotenv("config.env", override=True)

if path.exists("log.txt"):
    with open("log.txt", "w+") as f:
        f.truncate(0)


class CustomFormatter(Formatter):
    def format(self, record: LogRecord) -> str:
        return super().format(record).replace(gethostname(), "Aeon")


basicConfig(
    format="[%(asctime)s] - [%(name)s] - [%(levelname)s] - %(message)s",
    datefmt="%d-%b-%y %I:%M:%S %p",
    handlers=[
        FileHandler("log.txt"),
        StreamHandler(),
    ],
    level="INFO",
)

for handler in getLogger().handlers:
    handler.setFormatter(CustomFormatter(handler.formatter._fmt, handler.formatter.datefmt))

LOGGER = getLogger(__name__)

cpu_no = cpu_count()
threads = max(1, cpu_no // 2) # Dynamic threads
cores = "" # Not used directly if we remove taskset, or generate dynamically if needed

DOWNLOAD_DIR = "/app/downloads/"
intervals = {
    "status": {},
    "qb": "",
    "jd": "",
    "stopAll": False,
}
qb_torrents = {}
user_data = {}
aria2_options = {}
qbit_options = {}
nzb_options = {}
queued_dl = {}
queued_up = {}
non_queued_dl = set()
non_queued_up = set()
multi_tags = set()
task_dict_lock = None
queue_dict_lock = None
qb_listener_lock = None
jd_listener_lock = None
nzb_listener_lock = None
cpu_eater_lock = None
subprocess_lock = None
same_directory_lock = None
bot_start_time = 0
bot_loop = None
rss_dict = {}
auth_chats = {}
excluded_extensions = ["aria2", "!qB"]
included_extensions = []
drives_names = []
drives_ids = []
index_urls = []
shorteners_list = []

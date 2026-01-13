from re import match as re_match


def is_magnet(url: str):
    if not url or not isinstance(url, str):
        return False
    return bool(
        re_match(
            r"^magnet:\?.*xt=urn:(btih|btmh):([a-zA-Z0-9]{32,40}|[a-z2-7]{32}).*",
            url,
        )
    )


def is_url(url: str):
    if not url or not isinstance(url, str):
        return False
    return bool(
        re_match(
            r"^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?(\?[^#\s]*)?(#.*)?$",
            url,
        ),
    )


def is_gdrive_link(url: str):
    if not url or not isinstance(url, str):
        return False
    return "drive.google.com" in url or "drive.usercontent.google.com" in url


def is_telegram_link(url: str):
    if not url or not isinstance(url, str):
        return False
    return bool(
        re_match(
            r"^(https?:\/\/)?(www\.)?(t\.me|telegram\.me|tg:\/\/openmessage\?user_id=)",
            url,
        )
    )


def is_share_link(url: str):
    if not url or not isinstance(url, str):
        return False
    return bool(
        re_match(
            r"https?:\/\/.+\.gdtot\.\S+|https?:\/\/(filepress|filebee|appdrive|gdflix)\.\S+",
            url,
        ),
    )


def is_rclone_path(path: str):
    try:
        return bool(
            re_match(
                r"^(mrcc:)?(?!(magnet:|mtp:|sa:|tp:))(?![- ])[a-zA-Z0-9_\. -]+(?<! ):(?!.*\/\/).*$|^rcl$",
                path,
            ),
        )
    except Exception:
        return False


def is_gdrive_id(id_: str):
    if not id_ or not isinstance(id_, str):
        return False
    return bool(
        re_match(
            r"^(tp:|sa:|mtp:)?(?:[a-zA-Z0-9-_]{33}|[a-zA-Z0-9_-]{19})$|^gdl$|^(tp:|mtp:)?root$",
            id_,
        ),
    )

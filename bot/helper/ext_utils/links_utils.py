from re import compile as re_compile
from re import match as re_match

# Pre-compile regex patterns for better performance
_MAGNET_PATTERN = re_compile(
    r"^magnet:\?.*xt=urn:(btih|btmh):([a-zA-Z0-9]{32,40}|[a-z2-7]{32}).*"
)

_URL_PATTERN = re_compile(
    r"^(?!\/)(rtmps?:\/\/|mms:\/\/|rtsp:\/\/|https?:\/\/|ftp:\/\/)"
    r"?([^\/:]+:[^\/@]+@)?(www\.)?(?=[^\/:\s]+\.[^\/:\s]+)"
    r"([^\/:\s]+\.[^\/:\s]+)(:\d+)?(\/[^#\s]*[\s\S]*)?"
    r"(\?[^#\s]*)?(#.*)?$"
)

_TELEGRAM_PATTERN = re_compile(
    r"^(https?:\/\/)?(www\.)?(t\.me|telegram\.me|telegram\.dog)"
    r"(\/[a-zA-Z0-9_]+)?(\/\d+)?(-\d+)?$|^tg:\/\/openmessage\?user_id=\d+$"
)

_SHARE_LINK_PATTERN = re_compile(
    r"^https?:\/\/.+\.gdtot\.\S+$|"
    r"^https?:\/\/(filepress|filebee|appdrive|gdflix)\.\S+$"
)

_RCLONE_PATH_PATTERN = re_compile(
    r"^(mrcc:)?(?!(magnet:|mtp:|sa:|tp:))(?![- ])[a-zA-Z0-9_\. -]+(?<! ):"
    r"(?!.*\/\/).*$|^rcl$"
)

_GDRIVE_ID_PATTERN = re_compile(
    r"^(tp:|sa:|mtp:)?(?:[a-zA-Z0-9-_]{33}|[a-zA-Z0-9_-]{19})$|"
    r"^gdl$|^(tp:|mtp:)?root$"
)

# Google Drive domains
_GDRIVE_DOMAINS = {
    "drive.google.com",
    "drive.usercontent.google.com",
    "docs.google.com",
}


def is_magnet(url: str) -> bool:
    """
    Check if the given string is a valid magnet link.

    Args:
        url: The string to check

    Returns:
        bool: True if valid magnet link, False otherwise

    Examples:
        >>> is_magnet("magnet:?xt=urn:btih:abc123...")
        True
        >>> is_magnet("https://example.com")
        False
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_MAGNET_PATTERN.match(url))


def is_url(url: str) -> bool:
    """
    Check if the given string is a valid URL.
    Supports: http, https, ftp, rtmp, rtmps, mms, rtsp protocols.

    Args:
        url: The string to check

    Returns:
        bool: True if valid URL, False otherwise

    Examples:
        >>> is_url("https://example.com/path")
        True
        >>> is_url("not a url")
        False
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_URL_PATTERN.match(url))


def is_gdrive_link(url: str) -> bool:
    """
    Check if the given string is a Google Drive link.

    Args:
        url: The string to check

    Returns:
        bool: True if Google Drive link, False otherwise

    Examples:
        >>> is_gdrive_link("https://drive.google.com/file/d/abc123")
        True
        >>> is_gdrive_link("https://example.com")
        False
    """
    if not url or not isinstance(url, str):
        return False

    # Convert to lowercase for case-insensitive check
    url_lower = url.lower()
    return any(domain in url_lower for domain in _GDRIVE_DOMAINS)


def is_telegram_link(url: str) -> bool:
    """
    Check if the given string is a Telegram link.
    Supports: t.me, telegram.me, telegram.dog, and tg:// protocol.

    Args:
        url: The string to check

    Returns:
        bool: True if Telegram link, False otherwise

    Examples:
        >>> is_telegram_link("https://t.me/channel/123")
        True
        >>> is_telegram_link("tg://openmessage?user_id=123")
        True
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_TELEGRAM_PATTERN.match(url))


def is_share_link(url: str) -> bool:
    """
    Check if the given string is a file sharing link.
    Supports: gdtot, filepress, filebee, appdrive, gdflix domains.

    Args:
        url: The string to check

    Returns:
        bool: True if file sharing link, False otherwise

    Examples:
        >>> is_share_link("https://example.gdtot.com/file")
        True
        >>> is_share_link("https://filepress.com/file")
        True
    """
    if not url or not isinstance(url, str):
        return False
    return bool(_SHARE_LINK_PATTERN.match(url))


def is_rclone_path(path: str) -> bool:
    """
    Check if the given string is a valid rclone path.

    Args:
        path: The string to check

    Returns:
        bool: True if valid rclone path, False otherwise

    Examples:
        >>> is_rclone_path("remote:path/to/file")
        True
        >>> is_rclone_path("rcl")
        True
        >>> is_rclone_path("magnet:invalid")
        False
    """
    if not path or not isinstance(path, str):
        return False

    try:
        return bool(_RCLONE_PATH_PATTERN.match(path))
    except Exception:
        return False


def is_gdrive_id(id_: str) -> bool:
    """
    Check if the given string is a valid Google Drive file/folder ID.
    Supports prefixes: tp:, sa:, mtp: and special values: gdl, root.

    Args:
        id_: The string to check

    Returns:
        bool: True if valid Google Drive ID, False otherwise

    Examples:
        >>> is_gdrive_id("1abc123xyz789-_ABC")
        True
        >>> is_gdrive_id("tp:1abc123xyz789")
        True
        >>> is_gdrive_id("root")
        True
        >>> is_gdrive_id("invalid")
        False
    """
    if not id_ or not isinstance(id_, str):
        return False
    return bool(_GDRIVE_ID_PATTERN.match(id_))


def extract_gdrive_id(url: str) -> str | None:
    """
    Extract Google Drive file/folder ID from a Google Drive URL.

    Args:
        url: The Google Drive URL

    Returns:
        Optional[str]: The extracted ID or None if not found

    Examples:
        >>> extract_gdrive_id("https://drive.google.com/file/d/abc123/view")
        'abc123'
        >>> extract_gdrive_id("https://drive.google.com/open?id=xyz789")
        'xyz789'
    """
    if not is_gdrive_link(url):
        return None

    # Pattern 1: /d/{id}/ or /d/{id}
    match = re_match(r"https?://.*drive\.google\.com/.*\/d\/([a-zA-Z0-9-_]+)", url)
    if match:
        return match.group(1)

    # Pattern 2: ?id={id}
    match = re_match(
        r"https?://.*drive\.google\.com/.*[\?&]id=([a-zA-Z0-9-_]+)", url
    )
    if match:
        return match.group(1)

    # Pattern 3: /folders/{id}
    match = re_match(
        r"https?://.*drive\.google\.com/.*\/folders\/([a-zA-Z0-9-_]+)", url
    )
    if match:
        return match.group(1)

    return None


def get_link_type(url: str) -> str:
    """
    Determine the type of the given link/path.

    Args:
        url: The link or path to check

    Returns:
        str: The link type ('magnet', 'gdrive', 'telegram', 'share', 'rclone', 'url', 'unknown')

    Examples:
        >>> get_link_type("magnet:?xt=...")
        'magnet'
        >>> get_link_type("https://t.me/channel")
        'telegram'
    """
    if not url or not isinstance(url, str):
        return "unknown"

    if is_magnet(url):
        return "magnet"
    if is_telegram_link(url):
        return "telegram"
    if is_gdrive_link(url):
        return "gdrive"
    if is_share_link(url):
        return "share"
    if is_rclone_path(url):
        return "rclone"
    if is_url(url):
        return "url"

    return "unknown"


def sanitize_url(url: str) -> str:
    """
    Sanitize a URL by removing leading/trailing whitespace and common issues.

    Args:
        url: The URL to sanitize

    Returns:
        str: The sanitized URL
    """
    if not url or not isinstance(url, str):
        return ""

    # Remove leading/trailing whitespace
    url = url.strip()

    # Remove zero-width spaces and other invisible characters
    return url.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")


def is_valid_filename(filename: str) -> bool:
    """
    Check if a string is a valid filename (not a URL or path).

    Args:
        filename: The string to check

    Returns:
        bool: True if valid filename, False otherwise
    """
    if not filename or not isinstance(filename, str):
        return False

    # Check if it's not a URL or path
    if is_url(filename) or is_telegram_link(filename) or is_magnet(filename):
        return False

    # Check for invalid filename characters
    invalid_chars = ["/", "\\", ":", "*", "?", '"', "<", ">", "|"]
    return not any(char in filename for char in invalid_chars)

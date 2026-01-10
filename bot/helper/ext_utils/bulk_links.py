from re import split as re_split

from bot.helper.ext_utils.bot_utils import new_task


def filter_links(links_list, bulk_start, bulk_end):
    start = bulk_start if bulk_start > 0 else None
    end = bulk_end if bulk_end > 0 else None
    return links_list[start:end]


def get_links_from_message(text: str) -> list:
    """
    Extracts all links from a text string.

    Args:
        text: The text to extract links from.

    Returns:
        A list of links found in the text.
    """
    if not text:
        return []
    links = []
    for link in re_split(r"\s+", text):
        if link.startswith("http") or link.startswith("magnet"):
            links.append(link)
    return links


async def extract_bulk_links(message, bulk_start: str, bulk_end: str) -> list:
    """
    Extracts links from a message or a file attached to the message.

    Args:
        message: The Telegram message object.
        bulk_start: The starting index for bulk processing.
        bulk_end: The ending index for bulk processing.

    Returns:
        A list of links.
    """
    bulk_start = int(bulk_start)
    bulk_end = int(bulk_end)
    links = []
    if reply_to := message.reply_to_message:
        if (
            reply_to.document
            and reply_to.document.mime_type == "text/plain"
        ):
            file_ = await reply_to.download()
            with open(file_, "r") as f:
                lines = f.readlines()
            links = [line.strip() for line in lines if line.strip()]
            from os import remove
            remove(file_)
        elif reply_to.text:
            links = get_links_from_message(reply_to.text)

    if links:
        return filter_links(links, bulk_start, bulk_end)
    return []

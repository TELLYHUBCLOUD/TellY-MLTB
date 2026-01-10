from bot.helper.ext_utils.links_utils import is_gdrive_id


async def check_running_tasks(listener):
    all_limit = listener.user_dict.get("QUEUE_ALL")
    dl_limit = listener.user_dict.get("QUEUE_DOWNLOAD")
    up_limit = listener.user_dict.get("QUEUE_UPLOAD")
    return (
        all_limit or dl_limit or up_limit,
        all_limit,
        dl_limit,
        up_limit,
    )


async def stop_duplicate_check(listener):
    if (
        listener.is_leech
        or not listener.stop_duplicate
        or listener.same_dir
        or listener.select
        or not is_gdrive_id(listener.up_dest)
    ):
        return False, None

    return await listener.check_duplicate()


async def start_from_queued():
    from bot import (
        non_queued_dl,
        non_queued_up,
        queue_dict_lock,
        queued_dl,
        queued_up,
    )

    async with queue_dict_lock:
        if len(queued_dl) != 0:
            for key, value in list(queued_dl.items()):
                if len(non_queued_dl) < value[0]:
                    non_queued_dl.add(key)
                    value[1].set()
                    del queued_dl[key]
                    break
        if len(queued_up) != 0:
            for key, value in list(queued_up.items()):
                if len(non_queued_up) < value[0]:
                    non_queued_up.add(key)
                    value[1].set()
                    del queued_up[key]
                    break

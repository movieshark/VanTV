from datetime import datetime, timezone


def zulu_to_human_localtime(zulu_time: str):
    """
    Convert a Zulu time string to human-readable local time.

    :param zulu_time: The Zulu time string in the format 'YYYY-MM-DDTHH:MM:SS.sssZ'.
    :return: The human-readable local time string in the format 'YYYY-MM-DD HH:MM:SS'.
    """
    zulu_dt = datetime.strptime(zulu_time, "%Y-%m-%dT%H:%M:%S.%fZ")
    zulu_dt = zulu_dt.replace(tzinfo=timezone.utc)

    local_offset = datetime.now().astimezone().utcoffset()

    local_dt = zulu_dt + local_offset

    return local_dt.strftime("%Y-%m-%d %H:%M:%S")

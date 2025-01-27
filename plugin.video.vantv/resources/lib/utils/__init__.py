from datetime import datetime, timezone
from os import environ
from random import choice

import xbmc
from requests import Session
from resources.lib.utils import static as utils_static
from resources.lib.van import static
from xbmcaddon import Addon

addon = Addon()


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


def unix_to_epg_time(unix_time: int):
    """
    Convert a Unix timestamp to an EPG time string.

    :param unix_time: The Unix timestamp.
    :return: The EPG time string in the format '%Y%m%d%H%M%S %z'.
    """
    return datetime.fromtimestamp(unix_time, tz=timezone.utc).strftime(
        "%Y%m%d%H%M%S %z"
    )


def get_kodi_version() -> int:
    """
    Get the Kodi major version number.

    :return: The Kodi version.
    """
    return int(xbmc.getInfoLabel("System.BuildVersion").split(".")[0])


def is_android() -> bool:
    """
    Check if the platform is Android.

    :return: True if the platform is Android, False otherwise.
    """
    return xbmc.getInfoLabel("System.Platform.Android") or "ANDROID_STORAGE" in environ


def prepare_session() -> Session:
    """
    Prepare a requests session for use within the addon. Also sets
     the user agent to a random desktop user agent if it is not set.

    :return: The prepared session.
    """
    user_agent = addon.getSetting("useragent")
    if not user_agent:
        if is_android():
            addon.setSetting("useragent", choice(utils_static.android_user_agents))
        else:
            addon.setSetting("useragent", choice(utils_static.desktop_user_agents))
        user_agent = addon.getSetting("useragent")
    session = Session()
    session.headers.update(
        {
            "User-Agent": user_agent,
        }
    )
    return session


def prepare_device() -> None:
    """
    Prepare the device model for the addon. If the device model is not set,
     a random device model is chosen from the static device list.

    :return: None
    """
    device_model = addon.getSetting("devicemodel")
    _is_android = is_android()

    if (
        not device_model
        or (_is_android and device_model not in static.android_devices)
        or (not _is_android and device_model not in static.web_devices)
    ):
        if _is_android:
            device_model = choice(list(static.android_devices.keys()))
        else:
            device_model = choice(list(static.web_devices.keys()))
        addon.setSetting("devicemodel", device_model)

    device_properties = (
        static.android_devices.get(device_model)
        if _is_android
        else static.web_devices.get(device_model)
    )
    return device_properties

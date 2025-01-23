import xbmcaddon
import xbmcvfs
import xbmcgui
import xbmc

from traceback import format_exc

from requests import Session, HTTPError
from default import get_user_entitlements
from resources.lib.van import media_list, static
from urllib.parse import quote_plus, urlencode


def get_path(addon: xbmcaddon.Addon, is_epg: bool = False) -> str:
    """
    Check if the channel and epg path exists

    :param is_epg: Whether to check for the epg path
    :return: The path if it exists
    :raises IOError: If the path does not exist
    """
    path = addon.getSetting("channelexportpath")
    if is_epg:
        name = addon.getSetting("epgexportname")
    else:
        name = addon.getSetting("channelexportname")
    if not all([path, name]):
        return False
    if not xbmcvfs.exists(path):
        result = xbmcvfs.mkdirs(path)
        if not result:
            raise IOError(f"Failed to create directory {path}")
    # NOTE: we trust the user to enter a valid path
    # there is no sanitization
    return xbmcvfs.translatePath(f"{path}/{name}")


def export_channel_list(addon: xbmcaddon.Addon, session: Session) -> None:
    """
    Export channel list to an m3u file

    :param _session: requests.Session object
    :return: None
    """
    dialog = xbmcgui.Dialog()
    try:
        path = get_path(addon)
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30062),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30005),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    entitlements = get_user_entitlements(session)

    try:
        service_list = media_list.get_channel_list(
            session, static.get_api_base(), addon.getSetting("accesstoken")
        )
    except HTTPError as e:
        xbmc.log(format_exc(), xbmc.LOGERROR)
        # show error dialog and exit
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30019).format(
                status=e.response.status_code, body=e.response.text
            ),
        )
        exit()

    # m3u header
    output = "#EXTM3U\n\n"

    for service in service_list.get("services") or []:
        editorial = service.get("editorial", {})
        technical = service.get("technical", {})

        channel_id = editorial.get("id") or editorial.get("_id")
        drm_id = technical.get("drmId")
        channel_url = technical.get("NetworkLocation")
        name = editorial.get("longName", addon.getLocalizedString(30056))
        if not drm_id or not channel_url or not channel_id:
            # without a DRM ID or URL we can't play the stream
            # without a channel ID we can't uniquely identify the channel
            xbmc.log(
                f"Skipping channel {name}, missing DRM ID, URL or channel ID",
                xbmc.LOGDEBUG,
            )
            continue

        product_refs = technical.get("productRefs") or []
        if not any([product_ref in entitlements for product_ref in product_refs]):
            # user is not entitled to this channel
            xbmc.log(
                f"Skipping channel {name}, user not entitled",
                xbmc.LOGDEBUG,
            )
            continue

        # all items are added to a meta group for easy filtering
        groups = [addon.getAddonInfo("name")]

        genres = editorial.get("Categories") or []
        for genre in genres:
            groups.append(f"{genre.replace(';', ',')} ({addon.getAddonInfo('name')})")

        # for some reason that's a string
        is_adult = editorial.get("isAdult") or "" == "true"
        if is_adult:
            groups.append(f"18+ ({addon.getAddonInfo('name')})")

        # multiple groups are supported by IPTV Simple since v3.2.1
        # https://github.com/kodi-pvr/pvr.iptvsimple/blob/a5f312c20643889c2f73334be36bba995280fa6d/pvr.iptvsimple/changelog.txt#L582
        groups = ";".join(groups)

        icon = f"{static.get_imageservice_base()}/images/v1/image/channel/{channel_id}/logo?aspect=1x1&height=256&imageFormat=webp&width=256"

        # m3u entry
        # TODO: add catchup="vod" once we have catchup support
        output += f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{name}" tvg-logo="{icon}" group-title="{groups}",{name}\n'
        query = {
            "action": "play_channel",
            "id": drm_id,
            "extra": quote_plus(channel_url),
        }
        url = f"plugin://{addon.getAddonInfo('id')}/?{urlencode(query)}"
        output += f"{url}\n\n"

    try:
        with xbmcvfs.File(path, "w") as file:
            file.write(output)
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30062),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return

    dialog.notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(30063),
        xbmcgui.NOTIFICATION_INFO,
        sound=False,
    )

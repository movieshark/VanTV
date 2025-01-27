import threading
from time import time
from traceback import format_exc
from urllib.parse import quote_plus, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from default import authenticate, get_user_entitlements
from requests import HTTPError, Session
from resources.lib.utils import prepare_device, prepare_session, unix_to_epg_time
from resources.lib.van import media_list, static


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


def enc_xml(text) -> str:
    """
    Method to encode an XML string

    :param text: string to encode
    :return: encoded string
    """
    to_replace = {
        "&": "&amp;",
        "'": "&apos;",
        '"': "&quot;",
        ">": "&gt;",
        "<": "&lt;",
    }
    translation_table = str.maketrans(to_replace)
    return text.translate(translation_table)


def export_epg(
    addon: xbmcaddon.Addon,
    session: Session,
    from_time: str,
    to_time: str,
    is_killed: threading.Event = None,
) -> None:
    dialog = xbmcgui.Dialog()
    try:
        path = get_path(addon, is_epg=True)
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

    # get the list of channels the user is entitled to in a list
    # form with channel IDs

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

    channels = []

    for service in service_list.get("services") or []:
        if is_killed and is_killed.is_set():
            return

        editorial = service.get("editorial", {})
        technical = service.get("technical", {})

        channel_id = editorial.get("id") or editorial.get("_id")
        drm_id = technical.get("drmId")
        name = editorial.get("longName", addon.getLocalizedString(30056))
        if not drm_id or not channel_id:
            # without a DRM ID we can't play the stream
            # without a channel ID we can't uniquely identify the channel
            xbmc.log(
                f"Skipping channel {name}, missing DRM ID or channel ID",
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

        icon = f"{static.get_imageservice_base()}/images/v1/image/channel/{channel_id}/logo?aspect=1x1&height=256&imageFormat=webp&width=256"

        channels.append(
            {
                "id": channel_id,
                "name": name,
                "icon": icon,
            }
        )

    del service_list
    del entitlements

    temp_path = path + ".tmp"
    chunk_size = addon.getSettingInt("epgfetchinonereq")

    # write XML
    with xbmcvfs.File(temp_path, "w") as f:
        # based on info from https://github.com/XMLTV/xmltv/blob/master/xmltv.dtd

        # XML header
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write('<!DOCTYPE tv SYSTEM "xmltv.dtd">\n')

        # addon info
        f.write(
            f"<tv generator-info-name=\"{enc_xml(addon.getAddonInfo('name'))}\" generator-info-url=\"plugin://{addon.getAddonInfo('id')}/\">"
        )

        # channel data
        for channel in channels:
            if is_killed and is_killed.is_set():
                return
            f.write(f'<channel id="{enc_xml(channel["id"])}">')
            f.write(
                f'<display-name lang="hu">{enc_xml(channel["name"])}</display-name>'
            )
            f.write(f'<icon src="{enc_xml(channel["icon"])}"/>')
            f.write("</channel>")

        channel_ids = [channel["id"] for channel in channels]
        chunked_channel_ids = [
            channel_ids[i : i + chunk_size]
            for i in range(0, len(channel_ids), chunk_size)
        ]

        del channel_ids, channels

        for chunk in chunked_channel_ids:
            if is_killed and is_killed.is_set():
                return

            # NOTE: from and to time is in string format
            # it indicates the days back and forth from the current time
            # e.g. 1 and 1 means 1 day back and 1 day forth from the current time
            # but we can only fetch a max of 1 day back and forth in one request
            # so we need to fetch multiple times if the range is bigger

            from_days = int(from_time)
            to_days = int(to_time)
            start_time = int(time())

            time_ranges = []

            for i in range(-from_days, to_days):
                # NOTE: time could be '<num>d' format, but with unix time we make sure its exact
                # we can only request 1d worth of content per request, so if from is 1, to is 3,
                # we get [(-1, 0), (0, 1), (1, 2), (2, 3)] (in relative days here for better readability)
                _from_time = start_time + i * 86400
                _to_time = start_time + (i + 1) * 86400
                time_ranges.append((_from_time, _to_time))

            for _from_time, _to_time in time_ranges:
                try:
                    programs = media_list.get_epg(
                        session,
                        static.get_api_base(),
                        addon.getSetting("accesstoken"),
                        chunk,
                        _from_time,
                        _to_time,
                        [
                            "id",
                            "title",
                            "Description",
                            "Ratings",
                            "period",
                            "editorial.SeasonNumber",
                            "editorial.episodeNumber",
                            "Episode",
                            "editorial.contentType",
                            "editorial.Countries",
                            # "Year",
                            # "Genres",
                            # "Actors",
                            # NOTE: Unfortunately these aren't part of the provider's
                            # model when querying /epg. /epg/now and all other return it...
                            # If a developer sees it, please add it to the provider config :^). Thanks!
                        ],
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

                for channel_data in programs.get("results") or []:
                    if is_killed and is_killed.is_set():
                        return

                    channel_id = channel_data.get("channelId")
                    if not channel_id:
                        # can't continue without a channel ID
                        continue
                    for program in channel_data.get("programmes") or []:
                        if is_killed and is_killed.is_set():
                            return

                        epg_id = program.get("id")
                        period = program.get("period") or {}
                        start = period.get("start")
                        end = period.get("end")

                        if not all([epg_id, start, end]):
                            # can't continue at least without so much data
                            continue
                        start, end = unix_to_epg_time(start), unix_to_epg_time(end)

                        name = program.get("title") or addon.getLocalizedString(30056)
                        description = program.get("Description") or ""
                        editorial = program.get("editorial") or {}
                        season_number = editorial.get("SeasonNumber")
                        episode_number = editorial.get("episodeNumber")
                        content_type = editorial.get("contentType")
                        episode_name = program.get("Episode") or ""
                        countries = (editorial.get("Countries") or "").split(";")

                        icon = f"{static.get_imageservice_base()}/images/v1/image/movie/{epg_id}/banner?aspect=16x9&imageFormat=webp&width=320"
                        if content_type in ["episode", "tvshow"]:
                            icon = f"{static.get_imageservice_base()}/images/v1/image/episode/{epg_id}/episode?aspect=16x9&imageFormat=webp&width=320"

                        # epg content
                        f.write(
                            f'<programme start="{enc_xml(start)}" stop="{enc_xml(end)}" channel="{enc_xml(channel_id)}">'
                        )
                        f.write(f'<title lang="hu">{enc_xml(name)}</title>')
                        f.write(f'<desc lang="hu">{enc_xml(description)}</desc>')
                        f.write(f'<icon src="{enc_xml(icon)}"/>')

                        if all([episode_number, season_number]):
                            f.write(
                                f'<episode-num system="xmltv_ns">{enc_xml(str(season_number - 1))}.{enc_xml(str(episode_number - 1))}.</episode-num>'
                            )

                        # currently not supported by Kodi, but nice to have
                        countries = [
                            f"<country>{enc_xml(country)}</country>"
                            for country in countries
                        ]
                        if countries:
                            f.write("".join(countries))

                        if episode_name:
                            f.write(
                                f'<sub-title lang="hu">{enc_xml(episode_name)}</sub-title>'
                            )

                        f.write("</programme>")

                del programs

        f.write("</tv>")

    try:
        xbmcvfs.rename(temp_path, path)
    except IOError:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30064),
            xbmcgui.NOTIFICATION_ERROR,
        )
        return
    addon.setSetting("lastepgupdate", str(int(time())))

    if addon.getSettingBool("epgnotifoncompletion"):
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30065),
            xbmcgui.NOTIFICATION_INFO,
            sound=False,
        )


class EPGUpdaterThread(threading.Thread):
    """
    A thread that updates the EPG data in the background.
    """

    def __init__(
        self,
        addon: xbmcaddon.Addon,
        session: Session,
        from_time: str,
        to_time: str,
        frequency: int,
        last_updated: int,
    ):
        super().__init__()
        self.addon = addon
        self.session = session
        self.from_time = from_time
        self.to_time = to_time
        self.frequency = frequency
        self.last_updated = last_updated
        self.killed = threading.Event()
        self.failed_count = 0

    @property
    def now(self) -> int:
        """Returns the current time in unix format"""
        return int(time())

    @property
    def handle(self) -> str:
        """Returns the addon handle"""
        return f"[{self.addon.getAddonInfo('name')}]"

    def run(self) -> None:
        """
        EPG update thread's main loop.
        """
        while not self.killed.is_set():
            xbmc.log(
                f"{self.handle} EPG update: next update in {min(self.frequency, self.frequency - (self.now - self.last_updated))} seconds",
                xbmc.LOGINFO,
            )
            self.killed.wait(
                min(self.frequency, self.frequency - (self.now - self.last_updated))
            )
            if (
                not self.killed.is_set()
                and not self.failed_count > self.addon.getSettingInt("epgfetchtries")
            ):
                try:
                    authenticate(self.session)
                    export_epg(
                        self.addon,
                        self.session,
                        self.from_time,
                        self.to_time,
                        self.killed,
                    )
                    self.last_updated = self.now
                    self.failed_count = 0
                    xbmc.log(f"{self.handle} EPG update successful", xbmc.LOGINFO)
                except Exception:
                    self.failed_count += 1
                    xbmc.log(
                        f"{self.handle} EPG update failed: {format_exc()}",
                        xbmc.LOGERROR,
                    )
                    self.killed.wait(5)

    def stop(self) -> None:
        """
        Sets stop event to the thread.
        """
        self.killed.set()


# NOTE: we update settings too often and don't want to DoS the API
"""
class EPGMonitor(xbmc.Monitor):
    def __init__(self, *args, **kwargs):
        xbmc.Monitor.__init__(self)
        self.action = kwargs["action"]
        self.handle = kwargs["handle"]

    def onSettingsChanged(self):
        xbmc.log(
            f"{self.handle} Settings changed, restarting EPG updater", xbmc.LOGINFO
        )
        return self.action()


def restart_on_settings_change(thread: EPGUpdaterThread, handle: str) -> None:
    if thread and thread.is_alive():
        thread.stop()
        try:
            thread.join()
        except RuntimeError:
            pass
        xbmc.log(f"{handle} EPG updater stopped", xbmc.LOGINFO)
    epg_fetcher()
"""


def epg_fetcher():
    addon = xbmcaddon.Addon()

    handle = f"[{addon.getAddonInfo('name')}]"
    session = prepare_session()
    session.device_properties = prepare_device()

    auto_update = addon.getSettingBool("autoupdateepg")
    if not auto_update:
        xbmc.log(f"{handle} EPG updater disabled, aborting", xbmc.LOGINFO)
        return

    from_time = addon.getSetting("epgfrom")
    to_time = addon.getSetting("epgto")
    frequency = addon.getSettingInt("epgupdatefrequency")

    if not all([from_time, to_time, frequency]):
        xbmc.log(
            f"{handle} Missing EPG timeframe or frequency, EPG updater won't run",
            xbmc.LOGERROR,
        )
        return

    last_update = addon.getSetting("lastepgupdate")
    last_update = int(last_update) if last_update else 0

    epg_thread = EPGUpdaterThread(
        addon, session, from_time, to_time, frequency, last_update
    )
    epg_thread.start()
    xbmc.log(f"{handle} EPG updater started", xbmc.LOGINFO)

    # monitor = EPGMonitor(
    #    action=lambda: restart_on_settings_change(epg_thread, handle), handle=handle
    # )
    monitor = xbmc.Monitor()

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
    if epg_thread and epg_thread.is_alive():
        epg_thread.stop()
        try:
            epg_thread.join()
        except RuntimeError:
            pass
        xbmc.log(f"{handle} EPG updater stopped", xbmc.LOGINFO)


if __name__ == "__main__":
    # path triggered when the plugin is run as a script
    epg_fetcher()

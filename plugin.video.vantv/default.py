import urllib.parse
from json import dumps, loads
from os import environ
from random import choice
from sys import argv
from time import time
from traceback import format_exc

import inputstreamhelper
import licproxy_service
import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
from requests import HTTPError, Session
from resources.lib.myvodka import login as myvodka_login
from resources.lib.myvodka import static as myvodka_static
from resources.lib.myvodka import vtv
from resources.lib.utils import static as utils_static
from resources.lib.utils import zulu_to_human_localtime
from resources.lib.van import devices, enums, login, media_list, playback, static
from xbmcvfs import translatePath

addon = xbmcaddon.Addon()


def add_item(plugin_prefix, handle, name, action, is_directory, **kwargs) -> None:
    """
    Adds an item to the Kodi listing

    :param plugin_prefix: The plugin prefix.
    :param handle: The Kodi handle.
    :param name: The name of the item.
    :param action: The action to perform.
    :param is_directory: Whether the item is a directory.
    :param kwargs: Keyword arguments for additional parameters.
    :return: None:param kwargs: Additional parameters for the item.
    :return: None
    """
    url = f"{plugin_prefix}?action={action}"
    item = xbmcgui.ListItem(label=name)
    kodi_version = get_kodi_version()

    if kwargs.get("icon"):
        item.setArt({"thumb": kwargs["icon"], "icon": kwargs["icon"]})
    if kwargs.get("fanart"):
        item.setArt({"fanart": kwargs["fanart"]})
        item.setProperty("Fanart_Image", kwargs["fanart"])

    if kwargs.get("id"):
        url += f"&id={kwargs['id']}"
    if kwargs.get("extra"):
        url += f"&extra={kwargs['extra']}"
    if kwargs.get("is_livestream"):
        # see https://forum.kodi.tv/showthread.php?pid=2743328#pid2743328 to understand this hack
        # useful for livestreams to not to mark the item as watched + adds switch to channel context menu item
        # NOTE: MUST BE THE LAST PARAMETER in the URL
        url += "&pvr=.pvr"

    if not is_directory:
        item.setProperty("IsPlayable", "true")

    if kodi_version >= 20:
        infovideo = item.getVideoInfoTag()
        if "description" in kwargs:
            infovideo.setPlot(kwargs["description"])
        if "type" in kwargs:
            infovideo.setMediaType(kwargs["type"])
        if "year" in kwargs:
            infovideo.setYear(kwargs["year"])
        if "episode" in kwargs:
            infovideo.setEpisode(kwargs["episode"])
        if "season" in kwargs:
            infovideo.setSeason(kwargs["season"])
        if "show_name" in kwargs:
            infovideo.setTvShowTitle(kwargs["show_name"])
        if "genres" in kwargs:
            infovideo.setGenres(kwargs["genres"])
        if "country" in kwargs:
            infovideo.setCountries(kwargs["country"])
        if "director" in kwargs:
            infovideo.setDirectors(kwargs["director"])
        if "cast" in kwargs:
            infovideo.setCast(kwargs["cast"])
        if "mpaa" in kwargs:
            infovideo.setMpaa(kwargs["mpaa"])
        if "duration" in kwargs:
            infovideo.setDuration(kwargs["duration"])
    else:
        # Fallback for older versions
        info_labels = {}
        if "description" in kwargs:
            info_labels["plot"] = kwargs["description"]
        if "type" in kwargs:
            info_labels["mediatype"] = kwargs["type"]
        if "year" in kwargs:
            info_labels["year"] = kwargs["year"]
        if "episode" in kwargs:
            info_labels["episode"] = kwargs["episode"]
        if "season" in kwargs:
            info_labels["season"] = kwargs["season"]
        if "show_name" in kwargs:
            info_labels["tvshowtitle"] = kwargs["show_name"]
        if "genres" in kwargs:
            info_labels["genre"] = kwargs["genres"]
        if "country" in kwargs:
            info_labels["country"] = kwargs["country"]
        if "director" in kwargs:
            info_labels["director"] = kwargs["director"]
        if "cast" in kwargs:
            info_labels["cast"] = kwargs["cast"]
        if "mpaa" in kwargs:
            info_labels["mpaa"] = kwargs["mpaa"]
        if "duration" in kwargs:
            info_labels["duration"] = kwargs["duration"]
        item.setInfo(type="Video", infoLabels=info_labels)

    ctx_menu = []
    if kwargs.get("refresh"):
        ctx_menu.append((addon.getLocalizedString(30042), "Container.Refresh"))
    if kwargs.get("ctx_menu"):
        ctx_menu.extend(kwargs["ctx_menu"])
    item.addContextMenuItems(ctx_menu)

    xbmcplugin.addDirectoryItem(int(handle), url, item, is_directory)


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


def authenticate(session: Session) -> None:
    """
    Should be called before any API requests are made.
    Handles the login process and token refreshing. If reauthentication is necessary,
     this function will handle it.

    :param session: The requests session to use.
    :return: None
    """
    if not all([addon.getSetting("username"), addon.getSetting("password")]):
        return
    access_token_expiry = addon.getSetting("accessexpiry")
    if not access_token_expiry:
        # fresh login
        try:
            login_response = login.sign_in(
                session,
                static.get_api_base(),
                addon.getSetting("username"),
                addon.getSetting("password"),
                static.get_login_pubkey(),
                device_id=addon.getSetting("devicekey") or "",
            )
        except HTTPError as e:
            # some errors are pre-defined, we handle those with better error messages
            if (
                e.response.status_code == 403
                and "application/json" in e.response.headers.get("Content-Type", "")
                and e.response.json().get("code")
                and e.response.json().get("code")
                in enums.LoginInternalError._value2member_map_
            ):
                # if error is DEVICE_DELETED, we redo the entire login process
                # after clearing the device key
                if (
                    enums.LoginInternalError(e.response.json()["code"])
                    == enums.LoginInternalError.DEVICE_DELETED
                ):
                    addon.setSetting("devicekey", "")
                    addon.setSetting("accessexpiry", "")
                    return authenticate(session)

                dialog = xbmcgui.Dialog()
                dialog.ok(
                    addon.getAddonInfo("name"),
                    addon.getLocalizedString(30018).format(
                        error=enums.LoginInternalError._value2member_map_[
                            e.response.json().get("code")
                        ].name
                    ),
                )
                exit()
            # if we get an error code here, the login is most-likely invalid
            # so we show a dialog and open the settings
            message = ""
            if "application/json" in e.response.headers.get("Content-Type", ""):
                message = e.response.json().get("message")
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30016).format(
                    status=e.response.status_code, message=message
                ),
            )
            addon.openSettings()
            exit()
        _parse_login_response(login_response)
    elif int(access_token_expiry) < int(time()):
        # try to refresh the token if refresh token is still valid
        refresh_token_expiry = addon.getSetting("refreshexpiry")
        if int(refresh_token_expiry) > int(time()):
            try:
                refresh_response = login.refresh_access_token(
                    session,
                    static.get_api_base(),
                    addon.getSetting("refreshtoken"),
                )
            except HTTPError as e:
                # refresh token probably invalid, redo the whole login process
                addon.setSetting("accessexpiry", "")
                return authenticate(session)
            _parse_login_response(refresh_response)
        else:
            # refresh token invalid, redo the whole login process
            addon.setSetting("accessexpiry", "")
            return authenticate(session)


def _parse_login_response(response: dict) -> None:
    """
    Helper, that parses the login response and sets the necessary settings.

    :param response: The login response.
    :return: None
    """
    access_token = response.get("access_token")
    access_token_expiry = response.get("expires_in", 0) + int(time())
    refresh_token = response.get("refresh_token")
    refresh_token_expiry = response.get("refresh_expires_in", 0) + int(time())
    if not all([access_token, refresh_token]):
        # if we don't get the necessary tokens, show a dialog and open the settings
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30018).format(
                error="Missing tokens from login response"
            ),
        )
        addon.openSettings()
        raise ValueError("Missing tokens from login response")
    addon.setSetting("accesstoken", access_token)
    addon.setSetting("accessexpiry", str(access_token_expiry))
    addon.setSetting("refreshtoken", refresh_token)
    addon.setSetting("refreshexpiry", str(refresh_token_expiry))
    device_key = response.get("client_id")
    if device_key:
        addon.setSetting("devicekey", device_key)


def main_menu() -> None:
    """
    Renders the main menu of the addon.

    :return: None
    """
    # channel list
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30017),
        action="channel_list",
        is_directory=True,
        icon=translatePath(f"{addon.getAddonInfo('path')}/resources/media/live.png"),
    )
    # device list (OpenTV)
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30053),
        action="device_list",
        is_directory=True,
        icon=translatePath(f"{addon.getAddonInfo('path')}/resources/media/mobile.png"),
    )
    # device list (MyVodka)
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30041),
        action="myvodka_device_list",
        is_directory=True,
        icon=translatePath(f"{addon.getAddonInfo('path')}/resources/media/mobile.png"),
    )
    # about
    add_item(
        plugin_prefix=argv[0],
        handle=argv[1],
        name=addon.getLocalizedString(30031),
        action="about",
        is_directory=True,
        icon=translatePath(f"{addon.getAddonInfo('path')}/resources/media/about.png"),
    )
    xbmcplugin.endOfDirectory(int(argv[1]))


def channel_list(session: Session) -> None:
    """
    Renders the list of live channels. Subject to change. Currently unsorted,
     and unfiltered.

    :param session: The requests session.
    :return: None
    """
    service_list = media_list.get_channel_list(
        session, static.get_api_base(), addon.getSetting("accesstoken")
    ).get("services", [])
    for service in service_list:
        editorial = service.get("editorial", {})
        technical = service.get("technical", {})

        drm_id = technical.get("drmId")
        channel_url = technical.get("NetworkLocation")
        if not drm_id or not channel_url:
            # without a DRM ID or URL we can't play the stream
            continue
        name = editorial.get("longName")
        genres = editorial.get("Categories", [])
        # get first rating code from the list
        ratings = editorial.get("Ratings", [])
        rating = ratings[0].get("code") if ratings else None
        # if rating == "hu-unrated":
        #    rating = None
        if rating == "hu-12":
            rating = "TV-14"
        # NOTE: so far no other ratings were found

        channel_id = editorial.get("id")
        icon = None
        if channel_id:
            # NOTE: standard requests use much smaller 16:9 images
            # those look ugly within Kodi, so we use a higher resolution 1:1 image
            icon = f"{static.get_imageservice_base()}/images/v1/image/channel/{channel_id}/logo?aspect=1x1&height=256&imageFormat=webp&width=256"
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=name,
            id=drm_id,
            action="play_channel",
            is_directory=False,
            icon=icon,
            extra=urllib.parse.quote_plus(channel_url),
            genres=genres,
            mpaa=rating,
        )

    xbmcplugin.endOfDirectory(int(argv[1]))
    xbmcplugin.setContent(int(argv[1]), "videos")


def play(session: Session, channel_id: str, channel_url: str) -> None:
    """
    Plays the selected channel, sets up the session, prepares the inputstream,
     creates a license proxy thread and starts the playback. Then keeps monitoring
     the playback until it's stopped.

    :param session: The requests session.
    :param channel_id: The ID of the channel.
    :param channel_url: The URL of the channel.
    :return: None
    """
    try:
        content_token_response = playback.get_content_token(
            session, static.get_api_base(), addon.getSetting("accesstoken"), channel_id
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
    content_token = content_token_response.get("content_token")
    if not content_token:
        # show error dialog and exit
        dialog = xbmcgui.Dialog()
        dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30020))
        exit()

    try:
        session_setup_response = playback.setup_session(
            session, static.get_license_server_base(), content_token
        )
    except HTTPError as e:
        # NOTE: consider adding more errors from:
        # https://docs.nagra.com/connect-player-sdk-5-for-android-docs/5.36.x/Default/ssm-error-codes
        # (the provider only has a few of these implemented)
        if (
            e.response.status_code == 400
            and "application/json" in e.response.headers.get("Content-Type", "")
            and e.response.json().get("errorCode") == 1007
        ):
            # Maximum sessions limit reached
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30026),
            )
            exit()
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
    session_token = session_setup_response.get("sessionToken")
    if not session_token:
        # show error dialog and exit
        dialog = xbmcgui.Dialog()
        dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30020))
        exit()

    if addon.getSettingBool("httpmanifest"):
        # force the use of HTTP for the manifest
        # this is a workaround for the issue where Kodi doesn't trust the provider's cert
        # not recommended
        channel_url = (
            urllib.parse.urlparse(channel_url)._replace(scheme="http").geturl()
        )

    is_helper = inputstreamhelper.Helper("mpd", drm="com.widevine.alpha")

    license_url = (
        f"{static.get_license_server_base()}/wvls/contentlicenseservice/v1/licenses"
    )
    renewal_url = f"{static.get_license_server_base()}/ssm/v1/renewal-license-wv"
    teardown_url = f"{static.get_license_server_base()}/ssm/v1/sessions/teardown"

    licproxy_thread = licproxy_service.main_service(
        addon, license_url, renewal_url, session_token, teardown_url
    )

    play_item = xbmcgui.ListItem(path=channel_url)

    play_item.setContentLookup(False)
    play_item.setMimeType("application/dash+xml")

    play_item.setProperty("inputstream", is_helper.inputstream_addon)
    if get_kodi_version() < 21:
        play_item.setProperty("inputstream.adaptive.manifest_type", "mpd")
    play_item.setProperty("inputstream.adaptive.license_type", "com.widevine.alpha")
    common_headers = urllib.parse.urlencode(
        {"User-Agent": addon.getSetting("useragent")}
    )
    stream_headers = urllib.parse.urlencode(
        {"User-Agent": addon.getSetting("useragent"), "verifypeer": "false"}
    )
    if get_kodi_version() > 21:
        play_item.setProperty(
            "inputstream.adaptive.common_headers",
            common_headers,
        )
        # NOTE: curl doesn't trust the provider's cert
        # HTTPS playback is untested on older versions where
        # this property is not available. `verifypeer` is there
        # to potentially fix it, but it's not yet tested.
        # Ugly workaround: Switch back to HTTP playback in settings.
        play_item.setProperty(
            "inputstream.adaptive.config",
            '{"ssl_verify_peer":false}',
        )
    elif get_kodi_version() > 19:
        play_item.setProperty(
            "inputstream.adaptive.manifest_headers",
            stream_headers,
        )
        if get_kodi_version() != 20:
            play_item.setProperty(
                "inputstream.adaptive.stream_headers",
                stream_headers,
            )
    if not is_helper.check_inputstream():
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30021),
        )
        exit()

    if not is_android():
        user_agent = addon.getSetting("useragent")
    else:
        user_agent = static.android_nagra_user_agent

    license_headers = urllib.parse.urlencode(
        {
            "nv-authorizations": f"{content_token},{session_token}",
            "User-Agent": user_agent,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    )

    license_url = f'http://127.0.0.1:{licproxy_thread.port}/wv/license|{license_headers}|{{"challenge":"b{{SSM}}"}}|JBlicense'
    play_item.setProperty("inputstream.adaptive.license_key", license_url)

    xbmcplugin.setResolvedUrl(int(argv[1]), True, listitem=play_item)

    monitor = xbmc.Monitor()
    player = xbmc.Player()

    timeout = 120
    while not player.isPlaying() and not monitor.waitForAbort(1) and timeout > 0:
        timeout -= 1

    while player.isPlaying() and not monitor.waitForAbort(1):
        # when a user switches to another stream without stopping the previous one
        # Kodi will only trigger onPlayBackResumed, so we need to check if the url is the same
        # if they are different, stop the licproxy thread
        if player.isPlaying() and channel_url != player.getPlayingFile():
            break

    if licproxy_thread and licproxy_thread.is_alive():
        licproxy_thread.stop()
        try:
            licproxy_thread.join()
        except RuntimeError:
            pass


def device_list(session: Session) -> None:
    """
    Renders the list of devices for the current user.

    NOTE: None of this is supported by the official apps.

    :param session: The requests session.
    :return: None
    """
    try:
        device_list = devices.get_devices(
            session, static.get_api_base(), addon.getSetting("accesstoken")
        ).get("resourceSet", [])
    except HTTPError as e:
        xbmc.log(format_exc(), xbmc.LOGERROR)
        dialog = xbmcgui.Dialog()
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30019).format(
                status=e.response.status_code, body=e.response.text
            ),
        )
        exit()

    # sort devices by activation status and creation date (if available)
    device_list.sort(
        key=lambda x: (x.get("activationStatus"), x.get("created")), reverse=True
    )

    for device in device_list:
        device_id = device.get("_id")
        device_public_id = device.get("publicId")

        if not all([device_id, device_public_id]):
            continue

        device_type = device.get("deviceType")
        device_name = device.get("name")
        device_created = device.get("created")
        device_modified = device.get("modified")
        device_activated = device.get("activated")
        device_activation_status = device.get("activationStatus")
        device_information = (device.get("deviceInformation") or {}).get("device") or {}

        # device properties
        device_hardware = device_information.get("hardware") or {}
        device_os = device_information.get("OS") or {}
        device_screen = device_information.get("screen") or {}

        device_model = device_hardware.get("model")
        device_manufacturer = device_hardware.get("manufacturer")
        device_type = device_hardware.get("type")

        device_os_type = device_os.get("type")
        device_os_version = device_os.get("version")

        device_screen_height = device_screen.get("height")
        device_screen_width = device_screen.get("width")

        description = f"{addon.getLocalizedString(30011)}: {device_id}\n"
        if device_created:
            description += f"{addon.getLocalizedString(30046)}: {zulu_to_human_localtime(device_created)}\n"
        if device_modified:
            description += f"{addon.getLocalizedString(30047)}: {zulu_to_human_localtime(device_modified)}\n"
        if device_activated:
            description += f"{addon.getLocalizedString(30048)}: {zulu_to_human_localtime(device_activated)}\n"

        if device_activation_status:
            description += (
                f"{addon.getLocalizedString(30049)}: {device_activation_status}\n"
            )

        device_details = ""
        if device_manufacturer:
            device_details += f"{device_manufacturer}"
        if device_model:
            device_details += f" {device_model}"
        icon = None
        if device_type:
            device_details += f" ({device_type})"
            if device_type == "Mobile":
                icon = translatePath(
                    f"{addon.getAddonInfo('path')}/resources/media/mobile.png"
                )
            elif device_type == "Browser":
                icon = translatePath(
                    f"{addon.getAddonInfo('path')}/resources/media/web.png"
                )

        if device_details:
            description += (
                f"{addon.getLocalizedString(30050)}: {device_details.strip()}\n"
            )

        device_os_details = ""
        if device_os_type:
            device_os_details += f"{device_os_type}"
        if device_os_version:
            device_os_details += f" {device_os_version}"

        if device_os_details:
            description += (
                f"{addon.getLocalizedString(30051)}: {device_os_details.strip()}\n"
            )

        if device_screen_height and device_screen_width:
            description += f"{addon.getLocalizedString(30052)}: {device_screen_width}x{device_screen_height}\n"

        ctx_menu = []
        # we don't want the user to remove STBs accidentally
        if not (device_type == "MANAGED" or device_type == "STB"):
            # NOTE: deactivate doesn't actually remove the device, it just deactivates it
            # which causes unexpected issues with the provider
            # use MyVodka to remove the device instead
            # this is only here for educational purposes

            # ctx_menu.append(
            #    (
            #        addon.getLocalizedString(30039),
            #        f"RunPlugin({argv[0]}?action=del_device&device_id={device_public_id})",
            #    )
            # )
            ctx_menu.append(
                (
                    addon.getLocalizedString(30040),
                    f"RunPlugin({argv[0]}?action=rename_device&device_id={device_public_id})",
                )
            )

        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=device_name or device_id,
            description=description,
            action="dummy",
            is_directory=True,
            ctx_menu=ctx_menu,
            refresh=True,
            icon=icon,
        )

    xbmcplugin.endOfDirectory(int(argv[1]))
    xbmcplugin.setContent(int(argv[1]), "files")


def deactivate_device(session: Session, device_id: str) -> None:
    """
    Deactivates a device.

    NOTE: None of this is supported by the official apps.
    NOTE: Deactivating doesn't mean complete removal. For now it's
    not exposed, because it can cause unexpected issues. Use the myvodka
    device list to remove devices!

    :param session: The requests session.
    :param device_id: The ID of the device.

    :return: None
    """
    dialog = xbmcgui.Dialog()
    if dialog.yesno(addon.getAddonInfo("name"), addon.getLocalizedString(30054)):
        try:
            data = devices.deactivate_device(
                session,
                static.get_api_base(),
                addon.getSetting("accesstoken"),
                device_id,
            )
        except devices.DeviceError as e:
            dialog.ok(addon.getAddonInfo("name"), str(e))
            return
        except HTTPError as e:
            xbmc.log(format_exc(), xbmc.LOGERROR)
            dialog.ok(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30019).format(
                    status=e.response.status_code, body=e.response.text
                ),
            )
            exit()
        if data["modifiedCount"] > 0:
            dialog.notification(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30045),
                xbmcgui.NOTIFICATION_INFO,
                5000,
            )
        else:
            dialog.ok(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30055),
            )
        xbmc.executebuiltin("Container.Refresh")


def rename_device(session: Session, device_id: str) -> None:
    """
    Renames a device.

    NOTE: None of this is supported by the official apps.

    :param session: The requests session.
    :param device_id: The ID of the device.

    :return: None"""
    dialog = xbmcgui.Dialog()
    new_name = dialog.input(addon.getLocalizedString(30043))
    if not new_name:
        return
    try:
        data = devices.rename_device(
            session,
            static.get_api_base(),
            addon.getSetting("accesstoken"),
            device_id,
            new_name,
        )
    except HTTPError as e:
        xbmc.log(format_exc(), xbmc.LOGERROR)
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30019).format(
                status=e.response.status_code, body=e.response.text
            ),
        )
        exit()
    if data["modifiedCount"] > 0:
        dialog.notification(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30044),
            xbmcgui.NOTIFICATION_INFO,
            5000,
        )
    else:
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30055),
        )
    xbmc.executebuiltin("Container.Refresh")


def prepare_myvodka_session() -> Session:
    """
    Prepares a requests session for MyVodka.

    :return: requests session
    """
    session = Session()
    session.headers.update(
        {
            "Accept-Encoding": "gzip",
            "User-Agent": "okhttp/4.11.0",
            "Connection": "Keep-Alive",
        }
    )
    return session


def vodka_authenticate() -> None:
    """
    Handles login to MyVodka.

    :return: None
    """
    session = prepare_myvodka_session()

    # check if we have a token and if it's still valid
    expiry = xbmcgui.Window(static.HOME_ID).getProperty("kodi.van.myvodka_expiry")
    if not expiry or int(expiry) < int(time()):
        # show progress dialog
        dialog = xbmcgui.DialogProgress()
        dialog.create(addon.getAddonInfo("name"), addon.getLocalizedString(30032))
        try:
            response = myvodka_login.oxauth_login(
                session,
                myvodka_static.get_oxauth_url(),
                myvodka_static.get_oxauth_clientid(),
                myvodka_static.get_oxauth_clientsecret(),
                addon.getSetting("username"),
                addon.getSetting("password"),
                myvodka_static.get_oxauth_authorization(),
            )
        except myvodka_login.LoginException as e:
            dialog = xbmcgui.Dialog()
            dialog.ok(
                addon.getAddonInfo("name"),
                addon.getLocalizedString(30033).format(message=e),
            )
            exit()
        access_token = response["access_token"]
        dialog.update(50, addon.getLocalizedString(30034))
        response = myvodka_login.publicapi_login(
            session,
            f"{myvodka_static.get_publicapi_host()}/oauth2/token",
            myvodka_static.get_publicapi_clientid(),
            access_token,
        )
        access_token = response["access_token"]
        expiry = int(response["issued_at"] / 1000) + response["expires_in"]
        subscription_id = response.get("id_profile_svc_response", {}).get(
            "selectedSubscription", {}
        )["id"]
        dialog.update(75, addon.getLocalizedString(30035))
        response = myvodka_login.list_subscriptions(
            session,
            f"{myvodka_static.get_publicapi_host()}/mva-api/customerAPI/v1/accountAndSubscription",
            f"Bearer {access_token}",
            subscription_id,  # default subscription goes here
        )
        services = response.get("myServices", [])
        subscriptions = []
        for service in services:
            subscriptions = service.get("subscriptions", [])
            # filter to type: TV
            subscriptions = [
                subscription
                for subscription in subscriptions
                if subscription["type"] == "TV"
            ]
            if subscriptions:
                break
        if not subscriptions:
            dialog.close()
            dialog = xbmcgui.Dialog()
            dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30036))
            exit()
        dialog.close()
        if len(subscriptions) < 1:
            # show picker dialog
            dialog = xbmcgui.Dialog()
            subscription_names = [
                f"{subscription['name']} ({subscription['longAddress']})"
                for subscription in subscriptions
            ]
            index = dialog.select(
                addon.getLocalizedString(30037),
                subscription_names,
            )
            if index == -1:
                exit()
        else:
            index = 0
        subscription = subscriptions[index]
        subscription_id = subscription["id"]
        xbmcgui.Window(static.HOME_ID).setProperty(
            "kodi.van.myvodka_expiry", str(expiry)
        )
        xbmcgui.Window(static.HOME_ID).setProperty(
            "kodi.van.myvodka_access_token", access_token
        )
        xbmcgui.Window(static.HOME_ID).setProperty(
            "kodi.van.myvodka_individual_id", subscription_id
        )
    session.close()


def vodka_device_list() -> None:
    """
    Handles login to MyVodka if necessary and renders the device list.

    :param session: requests session
    :return: None
    """
    vodka_authenticate()
    session = prepare_myvodka_session()

    access_token = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_individual_id"
    )
    # request device list
    device_list = vtv.get_devices(
        session,
        f"{myvodka_static.get_publicapi_host()}/mva-api/productAPI/v2/vtv",
        f"Bearer {access_token}",
        individual_id,
    )

    connected_devices = device_list.get("connectedDevices", [])

    for device in connected_devices:
        device_id = device.get("id")
        device_name = device.get("name")
        device_type = device.get("type")

        icon = None
        if device_type == "Mobile":
            icon = translatePath(
                f"{addon.getAddonInfo('path')}/resources/media/mobile.png"
            )
        elif device_type == "Browser":
            icon = translatePath(
                f"{addon.getAddonInfo('path')}/resources/media/web.png"
            )

        description = f"{addon.getLocalizedString(30011)}: {device_id}\n{addon.getLocalizedString(30038)}: {device_type}"
        add_item(
            plugin_prefix=argv[0],
            handle=argv[1],
            name=device_name if device_name else device_id,
            description=description,
            action="dummy",  # clicking should do nothing
            is_directory=True,
            icon=icon,
            ctx_menu=[
                (
                    addon.getLocalizedString(30039),
                    f"RunPlugin({argv[0]}?action=del_vodka_device&device={urllib.parse.quote(dumps(device))})",
                ),
                (
                    addon.getLocalizedString(30040),
                    f"RunPlugin({argv[0]}?action=rename_vodka_device&device={urllib.parse.quote(dumps(device))})",
                ),
            ],
            refresh=True,
        )
    session.close()
    xbmcplugin.endOfDirectory(int(argv[1]))
    xbmcplugin.setContent(int(argv[1]), "files")


def rename_vodka_device(device: str) -> None:
    """
    Rename a MyVodka device.

    :param device_id: device id (udid)
    :return: None
    """
    # prompt for new name
    dialog = xbmcgui.Dialog()
    device_data = loads(device)
    device_name = device_data.get("name", "")
    new_name = dialog.input(
        addon.getLocalizedString(30043),
        device_name,
        type=xbmcgui.INPUT_TYPE_TEXT,
    )
    if not new_name:
        return
    # rename device
    vodka_authenticate()
    session = prepare_myvodka_session()
    access_token = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_individual_id"
    )
    device_id = device_data["id"]
    device_data["name"] = new_name
    try:
        if vtv.edit_device(
            session,
            f"{myvodka_static.get_publicapi_host()}/mva-api/productAPI/v2/vtv/device/{device_id}",
            f"Bearer {access_token}",
            individual_id,
            device_data,
        ):
            dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30044))
    except Exception as e:
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30033).format(message=e),
        )
    session.close()
    xbmc.executebuiltin("Container.Refresh")


def delete_vodka_device(device: str) -> None:
    """
    Delete a MyVodka device.

    :param device_id: device id (udid)
    :return: None
    """
    vodka_authenticate()
    session = prepare_myvodka_session()
    access_token = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_access_token"
    )
    individual_id = xbmcgui.Window(static.HOME_ID).getProperty(
        "kodi.van.myvodka_individual_id"
    )
    device_data = loads(device)
    device_id = device_data["id"]
    dialog = xbmcgui.Dialog()
    try:
        if vtv.delete_device(
            session,
            f"{myvodka_static.get_publicapi_host()}/mva-api/productAPI/v2/vtv/device/{device_id}",
            f"Bearer {access_token}",
            individual_id,
        ):
            dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30045))
    except Exception as e:
        dialog.ok(
            addon.getAddonInfo("name"),
            addon.getLocalizedString(30033).format(message=e),
        )
    session.close()
    xbmc.executebuiltin("Container.Refresh")


def about_dialog() -> None:
    """
    Show the about dialog.

    :return: None
    """
    dialog = xbmcgui.Dialog()
    dialog.textviewer(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(30029),
    )


if __name__ == "__main__":
    params = dict(urllib.parse.parse_qsl(argv[2].replace("?", "")))
    action = params.get("action")
    # session to be used for all requests
    session = prepare_session()
    # prepare the device model
    session.device_properties = prepare_device()
    # authenticate if necessary
    authenticate(session)

    if action is None:
        # while we are alpha, we show the dialog always
        about_dialog()
        if not all([addon.getSetting("username"), addon.getSetting("password")]):
            # show dialog to login
            dialog = xbmcgui.Dialog()
            dialog.ok(addon.getAddonInfo("name"), addon.getLocalizedString(30005))
            addon.openSettings()
            exit()
        main_menu()
    elif action == "channel_list":
        channel_list(session)
    elif action == "play_channel":
        play(session, params.get("id"), urllib.parse.unquote_plus(params.get("extra")))
    elif action == "device_list":
        device_list(session)
    # elif action == "del_device":
    #    deactivate_device(session, params.get("device_id"))
    elif action == "rename_device":
        rename_device(session, params.get("device_id"))
    elif action == "myvodka_device_list":
        vodka_device_list()
    elif action == "rename_vodka_device":
        rename_vodka_device(params.get("device"))
    elif action == "del_vodka_device":
        delete_vodka_device(params.get("device"))
    elif action == "about":
        about_dialog()

    session.close()

from json import loads

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs
from requests import Session


def run(addon: xbmcaddon.Addon, session: Session) -> None:
    from export_data import export_channel_list, export_epg

    # "IPTV Simple Client Setup Wizard"
    window_title = addon.getLocalizedString(30095)

    # Step 1: Welcome and explain the user what the wizard does
    if not xbmcgui.Dialog().yesno(
        window_title,
        addon.getLocalizedString(30096),
        yeslabel=addon.getLocalizedString(30097),
        nolabel=addon.getLocalizedString(30098),
    ):
        return

    # Step 2: Check if IPTV Simple Client is enabled and if not, prompt the user to enable it
    try:
        iptv_simple = xbmcaddon.Addon("pvr.iptvsimple")
    except RuntimeError:
        xbmc.executebuiltin("InstallAddon(pvr.iptvsimple)", wait=True)

    iptv_simple = xbmcaddon.Addon("pvr.iptvsimple")

    # Step 3: Check if IPTV Simple Client is enabled and if not, enable it
    is_enabled = xbmc.executeJSONRPC(
        '{"jsonrpc":"2.0","method":"Addons.GetAddonDetails","params":{"addonid":"pvr.iptvsimple","properties":["enabled"]},"id":1}',
    )
    if not loads(is_enabled).get("result", {}).get("addon", {}).get("enabled"):
        xbmc.executeJSONRPC(
            '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"pvr.iptvsimple","enabled":true},"id":1}',
            wait=True,
        )

    # Step 4: Tell user that we will request informations now they can change later in the addon settings
    xbmcgui.Dialog().ok(
        window_title,
        addon.getLocalizedString(30099),
    )

    # channelexportpath

    channel_path = xbmcgui.Dialog().browseSingle(
        0,  # ShowAndGetDirectory
        addon.getLocalizedString(30059),
        "files",
        "",
        False,
        False,
        xbmcvfs.translatePath(
            f"special://profile/addon_data/{addon.getAddonInfo('id')}/epg"
        ),
    )

    if not channel_path:
        return

    # try to create the directory if it does not exist
    created = xbmcvfs.exists(channel_path)
    if not created:
        created = xbmcvfs.mkdirs(channel_path)

    if not created:
        xbmcgui.Dialog().ok(
            window_title,
            addon.getLocalizedString(30100),
        )
        return

    addon.setSetting("channelexportpath", channel_path)

    # channelexportname

    channel_name = xbmcgui.Dialog().input(
        addon.getLocalizedString(30060),
        type=xbmcgui.INPUT_TYPE_TEXT,
        defaultt="channels.m3u",
    )

    if not channel_name:
        return

    addon.setSetting("channelexportname", channel_name)

    # epgexportname

    epg_name = xbmcgui.Dialog().input(
        addon.getLocalizedString(30068),
        type=xbmcgui.INPUT_TYPE_TEXT,
        defaultt="epg.xml",
    )

    if not epg_name:
        return

    addon.setSetting("epgexportname", epg_name)

    xbmcgui.Dialog().ok(
        window_title,
        addon.getLocalizedString(30101),
    )

    # epgfrom slider
    epg_from = xbmcgui.Dialog().select(
        addon.getLocalizedString(30069),
        # 1-7 days
        list(map(str, range(1, 8))),
        # 1 day is default
        preselect=0,
    )

    if epg_from == -1:
        return

    addon.setSetting("epgfrom", str(epg_from + 1))

    # epgto slider
    epg_to = xbmcgui.Dialog().select(
        addon.getLocalizedString(30070),
        # 1-7 days
        list(map(str, range(1, 8))),
        # 3 days is default
        preselect=2,
    )

    if epg_to == -1:
        return

    addon.setSetting("epgto", str(epg_to + 1))

    # epgudpdatefrequency
    epg_update = xbmcgui.Dialog().select(
        addon.getLocalizedString(30071),
        [
            addon.getLocalizedString(30072),  # 3 hours
            addon.getLocalizedString(30073),  # 6 hours
            addon.getLocalizedString(30074),  # 12 hours
            addon.getLocalizedString(30075),  # 24 hours
            addon.getLocalizedString(30076),  # 48 hours
            addon.getLocalizedString(30077),  # 72 hours
        ],
        preselect=2,
    )

    if epg_update == -1:
        return

    # choice needs to be converted to seconds
    epg_update = [10800, 21600, 43200, 86400, 172800, 259200][epg_update]

    addon.setSetting("epgupdatefrequency", str(epg_update))

    # epgfetchinonereq
    epg_fetch_in_one_req = xbmcgui.Dialog().select(
        addon.getLocalizedString(30078),
        [
            addon.getLocalizedString(30079),  # 1 channel
            addon.getLocalizedString(30080),  # 10 channels
            addon.getLocalizedString(30081),  # 20 channels
            addon.getLocalizedString(30082),  # 30 channels
        ],
        preselect=3,
    )

    if epg_fetch_in_one_req == -1:
        return

    # choice needs to be converted to number of channels
    epg_fetch_in_one_req = [1, 10, 20, 30][epg_fetch_in_one_req]

    addon.setSetting("epgfetchinonereq", str(epg_fetch_in_one_req))

    # epgfetchtries
    epg_fetch_tries = xbmcgui.Dialog().select(
        addon.getLocalizedString(30083),
        # 1-10 tries
        list(map(str, range(1, 11))),
        # 3 tries is default
        preselect=2,
    )

    if epg_fetch_tries == -1:
        return

    addon.setSetting("epgfetchtries", str(epg_fetch_tries + 1))

    # epgnotifoncompletion
    # does the user want a notification when the EPG fetch is completed?
    epg_notif_on_completion = xbmcgui.Dialog().yesno(
        window_title,
        addon.getLocalizedString(30102),
    )

    addon.setSetting(
        "epgnotifoncompletion", "true" if epg_notif_on_completion else "false"
    )

    # channel list export
    export_channel_list(addon, session)

    # EPG export
    from_time = addon.getSetting("epgfrom")
    to_time = addon.getSetting("epgto")

    dialog = xbmcgui.Dialog()
    dialog.notification(
        addon.getAddonInfo("name"),
        addon.getLocalizedString(30086).format(from_time=from_time, to_time=to_time),
        xbmcgui.NOTIFICATION_INFO,
        5000,
    )

    export_epg(addon, session, from_time, to_time)

    # Step 5: Tell user that the wizard is done, now comes the IPTV Simple Client setup
    xbmcgui.Dialog().ok(
        window_title,
        addon.getLocalizedString(30103),
    )

    # read addonsource/resources/assets/iptvsimple.xml
    with xbmcvfs.File(
        xbmcvfs.translatePath(
            f"special://home/addons/{addon.getAddonInfo('id')}/resources/assets/iptvsimple.xml"
        )
    ) as f:
        iptv_simple_xml = f.read()

    # replace the placeholders with the user settings
    # CHANNELLISTPATH
    iptv_simple_xml = iptv_simple_xml.replace(
        "CHANNELLISTPATH", xbmcvfs.translatePath(f"{channel_path}/{channel_name}")
    )

    # EPGURL
    iptv_simple_xml = iptv_simple_xml.replace(
        "EPGLISTPATH", xbmcvfs.translatePath(f"{channel_path}/{epg_name}")
    )

    # disable IPTV Simple Client temporarily
    xbmc.executeJSONRPC(
        '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"pvr.iptvsimple","enabled":false},"id":1}'
    )

    # save to special://profile/addon_data/pvr.iptvsimple/instance-settings-vantv.xml"
    with xbmcvfs.File(
        xbmcvfs.translatePath(
            "special://profile/addon_data/pvr.iptvsimple/instance-settings-76616.xml"
        ),
        "w",
    ) as f:
        f.write(iptv_simple_xml)

    xbmc.sleep(3000)

    # enable IPTV Simple Client
    xbmc.executeJSONRPC(
        '{"jsonrpc":"2.0","method":"Addons.SetAddonEnabled","params":{"addonid":"pvr.iptvsimple","enabled":true},"id":1}'
    )

    # Step 6: Tell user that the IPTV Simple Client setup is done
    xbmcgui.Dialog().ok(
        window_title,
        addon.getLocalizedString(30104),
    )

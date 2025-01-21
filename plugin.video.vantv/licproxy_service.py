import threading
from base64 import b64decode, b64encode
from json import load
from random import randint
from socketserver import ThreadingMixIn
from traceback import format_exc
from unicodedata import normalize
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

import requests
import xbmc
import xbmcaddon
from bottle import default_app, hook, request, response, route
from default import authenticate, is_android, prepare_session

"""
This file contains a lightweight web server. Don't worry, it only runs
when you have an active playback.

Unfortunately the provider implements its Widevine DRM support with a few
 non standard quirks. Kodi's ISA has no support for those. We need to handle
 those ourselves.
 
This module is a workaround for the following issues:
- The provider requires a session token for every request. This needs to be
  fetched and updated frequently.
- DRM sessions are limited to 2 concurrent sessions every 5 minutes. We need
  to send a teardown call to the provider to end the session.
- The provider requires a renewal call every 5 minutes to keep the CDM session
  alive. ISA would send these updates to the wrong endpoint with the wrong tokens.
- Android requires raw challenges for the initial license request and JSON for 
  renewals. ISA has no option to switch between raw and JSON challenges between
  renewals and initial requests in the same session.
"""


class SilentWSGIRequestHandler(WSGIRequestHandler):
    """Custom WSGI Request Handler with logging disabled"""

    protocol_version = "HTTP/1.1"

    def log_message(self, *args, **kwargs) -> None:
        """Disable log messages"""
        pass


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
    """Multi-threaded WSGI server"""

    allow_reuse_address = True
    daemon_threads = True
    timeout = 1


@hook("before_request")
def set_server_header() -> None:
    """
    Sets a Server header with the app's name for all successful responses.

    :return: None
    """
    response.set_header("Server", request.app.config["name"])


@route("/")
def index() -> str:
    """
    Returns a welcome message for the root path.
    Useful for checking if the service is running.

    :return: The welcome message.
    """
    response.content_type = "text/plain"
    return request.app.config["welcome_text"]


@route("/wv/license", method=["POST"])
def license() -> dict:
    """
    License proxy route for Widevine license requests.
    This is a workaround, because the policy specifies a 5 minute license validity.
    However renewal in ISA would hit the same endpoint instead of the renewal one.

    This method exposes a simple proxy that transparently forwards the request to the correct
     endpoint and also takes care of renewing the session token.

    For Android, initial license requests must be made with raw challenges while ChromeCDM
     requires JSON formatted challenges. However renewals are using JSON in both cases.
     This is also not supported by ISA. So we seamlessly convert JSON to raw challenges
     whenever necessary.

    :return: The proxied response (JSON).
    """
    app_config = request.app.config
    session = app_config["session"]
    license_url = app_config["license_url"]
    renewal_url = app_config["renewal_url"]
    session_token = app_config["session_token"]

    try:
        authenticate(session)
    except:
        xbmc.log(f"Failed to authenticate: {format_exc()}", xbmc.LOGERROR)
        response.status = 500
        return {"error": "Failed to authenticate"}

    target_url = license_url if not app_config.get("renewing", False) else renewal_url

    headers = dict(request.headers)
    if "Host" in headers:
        del headers["Host"]

    request_data = request.body

    if app_config.get("renewing", False):
        headers["Nv-Authorizations"] = session_token
    elif is_android():
        xbmc.log(f"Android detected, sending raw challenge instead", xbmc.LOGDEBUG)
        headers["Content-Type"] = "application/octet-stream"
        del headers["Accept"]
        request_data = load(request_data)
        xbmc.log(f"Challenge: {request_data}", xbmc.LOGDEBUG)
        request_data = b64decode(request_data["challenge"])

    xbmc.log(f"Proxying request to {target_url} with headers {headers}", xbmc.LOGDEBUG)

    try:
        proxied_response = session.post(
            url=target_url,
            headers=headers,
            data=request_data,
            params=request.query.decode(),
        )
        proxied_response.raise_for_status()
    except:
        xbmc.log(f"Request to {target_url} failed: {format_exc()}", xbmc.LOGERROR)
        response.status = 502
        return {"error": "Failed to proxy request"}

    # these headers would mess with ISA/libcurl, therefore we remove them
    # necessary content-length header is calculated either way by the web server
    if (
        "Transfer-Encoding" in proxied_response.headers
        and proxied_response.headers["Transfer-Encoding"] == "chunked"
    ):
        del proxied_response.headers["Transfer-Encoding"]
    if (
        "Content-Encoding" in proxied_response.headers
        and proxied_response.headers["Content-Encoding"] == "gzip"
    ):
        del proxied_response.headers["Content-Encoding"]
    if "Content-Length" in proxied_response.headers:
        del proxied_response.headers["Content-Length"]
    if "Connection" in proxied_response.headers:
        del proxied_response.headers["Connection"]

    xbmc.log(f"Proxy response headers: {proxied_response.headers}", xbmc.LOGDEBUG)

    if "application/json" in proxied_response.headers["Content-Type"]:
        data = proxied_response.json()
    else:
        # first request on Android is a raw challenge
        data = proxied_response.content

    response.status = proxied_response.status_code
    for key, value in proxied_response.headers.items():
        if key == "Content-Type" and "application/octet-stream" in value:
            response.content_type = "application/json"
        else:
            response.set_header(key, value)

    if "application/octet-stream" in proxied_response.headers["Content-Type"]:
        data = {"license": [b64encode(data).decode("utf-8")]}

    if app_config.get("renewing", False) and "sessionToken" in data:
        app_config["session_token"] = data["sessionToken"]
        xbmc.log(
            f"Updated sessionToken for future requests: {data['sessionToken']}",
            xbmc.LOGDEBUG,
        )
    elif (
        not app_config.get("renewing", False)
        and proxied_response.ok
        and request_data != b"\x08\x04"
    ):
        # Android requests a cert challenge with a Server Cert (\x08\x04) challenge
        # we must skip that one
        app_config["renewing"] = True
        xbmc.log("Switching to renewal mode for /wv/license calls", xbmc.LOGDEBUG)

    xbmc.log(f"Proxy response: {data}", xbmc.LOGDEBUG)

    return data


class WebServerThread(threading.Thread):
    def __init__(self, httpd: WSGIServer, port: int, teardown_url: str) -> None:
        threading.Thread.__init__(self)
        self.web_killed = threading.Event()
        self.httpd = httpd
        self.port = port
        self.teardown_url = teardown_url

    def run(self) -> None:
        """
        Starts the web server and handles requests until a stop signal is received.

        :return: None
        """
        while not self.web_killed.is_set():
            self.httpd.handle_request()

    def stop(self) -> None:
        """
        Stops the web server and sends a teardown call to the provider.
        Use this method to stop the web server!

        :return: None
        """
        if not self.web_killed.is_set():
            self.send_teardown()
        self.web_killed.set()

    def send_teardown(self) -> None:
        """
        The provider requires a teardown call which is used to tell the
         provider that the playback session has ended. If we don't send this,
         the provider won't let us keep more than 2 concurrent sessions every
         5 minutes.

        :return: None
        """
        app_config = self.httpd.app.config
        session_token = app_config["session_token"]
        headers = {"Nv-Authorizations": session_token}
        xbmc.log(
            f"Sending teardown call to {self.teardown_url} with headers {headers}",
            xbmc.LOGDEBUG,
        )
        try:
            response = requests.post(self.teardown_url, json={}, headers=headers)
            response.raise_for_status()
        except requests.RequestException:
            xbmc.log(f"Teardown call failed: {format_exc()}", xbmc.LOGERROR)
        xbmc.log(f"Teardown call response: {response.text}", xbmc.LOGDEBUG)


def main_service(
    addon: xbmcaddon.Addon,
    license_url: str,
    renewal_url: str,
    session_token: str,
    teardown_url: str,
) -> WebServerThread:
    """
    Main service method that handles the creation of a license proxy
     thread. Does port selection and starts the web server.
    Call this method to start the web server.

    :param addon: The addon instance.
    :param license_url: The license URL to proxy.
    :param renewal_url: The renewal URL to proxy.
    :param session_token: The session token to use.
    :param teardown_url: The teardown URL to use.

    :return: The web server thread.
    """
    name = f"{addon.getAddonInfo('name')} v{addon.getAddonInfo('version')}"
    name = normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    handle = f"[{name}]"
    app = default_app()
    welcome_text = f"{name} Web Service"
    app.config["name"] = name
    app.config["welcome_text"] = welcome_text
    app.config["license_url"] = license_url
    app.config["renewal_url"] = renewal_url
    app.config["session_token"] = session_token
    app.config["session"] = prepare_session()
    minport = addon.getSettingInt("minport")
    maxport = addon.getSettingInt("maxport")
    if minport > maxport or minport < 1024 or maxport > 65535:
        raise ValueError("Invalid port range")
    tries = 0
    while tries < 10:
        port = randint(minport, maxport)
        xbmc.log(f"{handle} Trying port {port} ({tries})...", xbmc.LOGINFO)
        try:
            httpd = make_server(
                addon.getSetting("webaddress"),
                port,
                app,
                server_class=ThreadedWSGIServer,
                handler_class=SilentWSGIRequestHandler,
            )
            break
        except OSError as e:
            if e.errno == 98:
                tries += 1
                xbmc.log(
                    f"{handle} Web service: port {port} already in use",
                    xbmc.LOGERROR,
                )
                return
            raise
    if tries == 10:
        xbmc.log(f"{handle} Web service: no available ports", xbmc.LOGERROR)
        raise OSError("No available ports")

    httpd.app = app
    xbmc.log(f"{handle} Web service starting", xbmc.LOGINFO)
    web_thread = WebServerThread(httpd, port, teardown_url)
    web_thread.start()
    return web_thread


if __name__ == "__main__":
    monitor = xbmc.Monitor()
    addon = xbmcaddon.Addon()
    web_thread = main_service(addon)

    while not monitor.abortRequested():
        if monitor.waitForAbort(1):
            break
    if web_thread and web_thread.is_alive():
        web_thread.stop()
        try:
            web_thread.join()
        except RuntimeError:
            pass
    xbmc.log(f"[{addon.getAddonInfo('name')}] Web service stopped", xbmc.LOGINFO)

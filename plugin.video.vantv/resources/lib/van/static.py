from base64 import b64decode
from functools import wraps

import xbmcgui
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

_key = bytes.fromhex("6f6e65747670617373776f7264020202")
_iv = bytes.fromhex("e81b70e7ea32d0d781e3294740a2f288")

nv_tenant_id = "nagra"
nv_tenant_id_2 = "FIGP0HS7"
sso_service_id = "4iGSSO"
content_device_type = "device"
android_nagra_user_agent = "Android-SDK-5.34.0"

web_devices = {
    "chrome_generic": {
        "hardware_model": "Chrome",
        "hardware_manufacturer": "Windows",
        "hardware_type": "Browser",
        "os_type": "Windows",
        "os_version": "x86_64",
        "nagra_device_type": "Browser",
        "nagra_target": "tv",
        "screen_width": 1920,
        "screen_height": 1080,
        "playout_device_class": "browser",
    }
}

android_devices = {
    "pixel_5": {
        "hardware_model": "Pixel 5",
        "hardware_manufacturer": "Google",
        "hardware_type": "Mobile",
        "os_type": "Android",
        "os_version": "14",
        "nagra_device_type": "Android",
        "nagra_target": "mobile",
        "screen_width": 1080,
        "screen_height": 2340,
        "playout_device_class": "mobileDevice",
    },
    "pixel_6": {
        "hardware_model": "Pixel 6",
        "hardware_manufacturer": "Google",
        "hardware_type": "Mobile",
        "os_type": "Android",
        "os_version": "15",
        "nagra_device_type": "Android",
        "nagra_target": "mobile",
        "screen_width": 1080,
        "screen_height": 2400,
        "playout_device_class": "mobileDevice",
    },
    "pixel_7": {
        "hardware_model": "Pixel 7",
        "hardware_manufacturer": "Google",
        "hardware_type": "Mobile",
        "os_type": "Android",
        "os_version": "15",
        "nagra_device_type": "Android",
        "nagra_target": "mobile",
        "screen_width": 1080,
        "screen_height": 2400,
        "playout_device_class": "mobileDevice",
    },
    "pixel_8": {
        "hardware_model": "Pixel 8",
        "hardware_manufacturer": "Google",
        "hardware_type": "Mobile",
        "os_type": "Android",
        "os_version": "15",
        "nagra_device_type": "Android",
        "nagra_target": "mobile",
        "screen_width": 1080,
        "screen_height": 2400,
        "playout_device_class": "mobileDevice",
    },
}

HOME_ID = 10000


def cache_result(func):
    """
    Simple decorator to cache the result of a function in Kodi's property storage.
    Useful if we don't want to recompute the same result multiple times (e.g. for encrypted static keys).

    The cache key is generated based on the function name and arguments.

    :param func: The function to cache
    :return: The wrapped function
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        # Generate a cache key based on function name and arguments
        cache_key = (func.__name__, args, frozenset(kwargs.items()))

        # Check if the result is already in the cache
        cached_result = xbmcgui.Window(HOME_ID).getProperty(
            "kodi.van.static." + str(cache_key)
        )
        if cached_result:
            return cached_result

        # If not in cache, compute the result and store it
        result = func(*args, **kwargs)
        xbmcgui.Window(HOME_ID).setProperty("kodi.van.static." + str(cache_key), result)
        return result

    return wrapper


def _decrypt_string(input: str) -> str:
    """
    Decrypts a string using AES-128-CBC with PKCS7 padding

    :param input: Encrypted string
    :return: Decrypted string
    """
    cipher = AES.new(_key, AES.MODE_CBC, _iv)
    return unpad(cipher.decrypt(b64decode(input)), 16, style="pkcs7").decode("utf-8")


@cache_result
def get_login_pubkey() -> str:
    c = "oe4agP5GyCeFVJtrdt7XdUUlUI10V4FYbn5p7Xo/05y+kD1XI6gpHKQv0IGkEqHMUE4Dt1/3nsXaWS51x3/izuOqloL0G2ESJQhjtTVgu5TO3VHlL+HMcv4fArE61douCxfFVlzb7rEm9n+mAGq2d5ZelfOOkii2T1EgSp1m1jknLHOyY1Y4zRqmPb7DQsWGoY91FWvVNAKr5gXgHG/BZFV9gO3RCdJyIch6K/rfMWpzAGR3gOelDLSqphdNAbFGwjVjn4nb5jYuKf1302RglV1zjpY9t89LZJnRwFfXZ2D4tgRRRxNsf9PSDgIdrolKQqTfK4CynXyu2E634H82qTu1/utmyObR+dn+lTKHh57s9n15ThQH2WUtspUcJaaT5zUKAn8G0gnfK8pxC4ihVEIg0qLHNZ0ZGnviJyrh179UBGMYB9tEXozD8Q9BNlOo8YJuihBRujsXW9Um2icRYVGmdb/9WLA1HM/6ANPZC/0semUl7k60699mfC0zVaVAlyDaEqH6PVHLxdiMEagT5WT4Yrh0ily3xrvLhv810bq1nny3yOEW+UQL0HNVf2DUd/rE3OGW1NimbIgpcy4/qmeDCOFlLT4L5ijFVJnSYcE="
    return _decrypt_string(c)


@cache_result
def get_api_base() -> str:
    c = "FsseRYMdFBdKMJGyFXOWKerHbqqqZQ1iMOR+2O2cSTRljkunN3rAmVwoJCk2ImZU"
    return _decrypt_string(c)


@cache_result
def get_imageservice_base() -> str:
    c = "cqmsqm8Aa3ShXqqQ81awctgyAF7XijJzz/NcR9jEHSduqeh3rK8MKMmrkX0F6d9K"
    return _decrypt_string(c)


@cache_result
def get_license_server_base() -> str:
    c = "iVpMcaACmUAkqkqi2VnXd74GOREscvqK2HOVYZop+asjjcXaL788A/pjF9o+a2x+"
    return _decrypt_string(c)

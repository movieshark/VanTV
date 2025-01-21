from base64 import b64decode
from functools import wraps

import xbmcgui
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import unpad

_key = bytes.fromhex("6f6e65747670617373776f7264020202")
_iv = bytes.fromhex("e81b70e7ea32d0d781e3294740a2f288")

scope = "openid lp_individual"
grant = "password"
grant_type = "urn:ietf:params:oauth:grant-type:jwt-bearer"

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
def get_oxauth_url() -> str:
    c = "ictzCSnMUWy0egu9rFpFLLj7+Wwj3+xQXxw63aZ9O8/AnW32jt8S8mMnn4L0xigg"
    return _decrypt_string(c)


@cache_result
def get_oxauth_clientid() -> str:
    c = "UJ+us9KiNPkS5JzLeJnkXG8KTAsaopbGZHfujgDqrAuefrRE5AzYMMPJjRYag9EO"
    return _decrypt_string(c)


@cache_result
def get_oxauth_clientsecret() -> str:
    c = "B7SDM2G6fNXC6+AeACBblFBWHGtl1GzQfE8A82X+mU0="
    return _decrypt_string(c)


@cache_result
def get_oxauth_authorization() -> str:
    c = "IyhJwSG38+KOCjqQGoGSoChbBZfrgds0WCzbiI+nyk7ycOak/cS+NLdN1uPtepqqLVNoQaCPqogHUnhjNVBlEHLg5eNHDShsqOR3K/Q72Ek7UZgirIahgvF+RS+1ohVG"
    return _decrypt_string(c)


@cache_result
def get_publicapi_host() -> str:
    c = "jFUxGlGF+NZAIF3SjhtN7PY4EobRigRoFxoqi6e+hQs="
    return _decrypt_string(c)


@cache_result
def get_publicapi_clientid() -> str:
    c = "i41RCRzLXlNPD84O4AygiyRrx8Cdqdwh4U8cH2GTbcCn5Aa1CntXLLYLZNvXYNHA"
    return _decrypt_string(c)

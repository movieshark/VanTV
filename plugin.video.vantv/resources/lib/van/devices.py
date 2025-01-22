from requests import Session

"""
Please note that the following isn't part of the original platform.
Therefore it isn't used anywhere by the official apps.
Most of it came from own research and documentation.
"""


class DeviceError(Exception):
    """Raised when a device action fails"""

    def __init__(self, message: str, code: int = 0) -> None:
        super().__init__(f"{message} (code: {code})")
        self.code = code


def get_devices(session: Session, api_base: str, access_token: str):
    """
    Get the list of devices for the current user.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.

    :return: The device list in JSON format.
    """
    params = {
        "limit": 10000,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    response = session.get(
        f"{api_base}/adm/v1/user/devices",
        params=params,
        headers=headers,
    )
    response.raise_for_status()
    json_data = response.json()
    return json_data


def deactivate_device(
    session: Session, api_base: str, access_token: str, device_id: str
):
    """
    Deactivate a device. Use it with caution. It does NOT remove the device.

    Result of own research, docs is wrong about the endpoint.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.
    :param device_id: The device ID to deactivate.

    :return: The device deactivation response in JSON format.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    response = session.put(
        f"{api_base}/adm/v1/user/devices/{device_id}/deactivate",
        headers=headers,
    )
    json_data = response.json()
    if json_data.get("errorCode", 0) != 0:
        raise DeviceError(
            response.json().get("message", "Unknown error"),
            response.json().get("errorCode", 0),
        )
    response.raise_for_status()
    return json_data


def rename_device(
    session: Session, api_base: str, access_token: str, device_id: str, name: str
):
    """
    Rename a device.

    Result of own research, docs is wrong about the endpoint.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.
    :param device_id: The device ID to rename.

    :return: The device renaming response in JSON format.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    response = session.put(
        f"{api_base}/adm/v1/user/devices/{device_id}/name",
        headers=headers,
        json={"name": name},
    )
    response.raise_for_status()
    return response.json()

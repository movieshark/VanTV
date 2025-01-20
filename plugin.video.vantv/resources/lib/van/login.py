from requests import Session
from resources.lib.van import misc, static


def sign_in(
    session: Session,
    api_base: str,
    username: str,
    password: str,
    public_key: str,
    device_id: str = "",
) -> dict:
    """
    Handles both fresh and existing device sign-ins.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param username: The account's username.
    :param password: The account's password.
    :param public_key: The public key used for password encryption.
    :param device_id: The device ID (empty string for fresh sign-ins).

    :return: The login response in JSON format.
    """
    data = {
        "parameters": [
            {"name": "username", "value": username},
            {"name": "password", "value": misc.encrypt_password(password, public_key)},
        ],
    }
    if device_id:
        data["clientId"] = device_id
    else:
        data["deviceInformation"] = {
            "playoutDeviceClass": session.device_properties["playout_device_class"],
            "device": {
                "screen": {
                    "height": session.device_properties["screen_height"],
                    "width": session.device_properties["screen_width"],
                },
                "hardware": {
                    "model": session.device_properties["hardware_model"],
                    "manufacturer": session.device_properties["hardware_manufacturer"],
                    "type": session.device_properties["hardware_type"],
                },
                "OS": {
                    "type": session.device_properties["os_type"],
                    "version": session.device_properties["os_version"],
                },
            },
        }
    headers = {
        "x-auth-service-id": static.sso_service_id,
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
        "nv-tenant-id": static.nv_tenant_id,
    }
    response = session.post(f"{api_base}/ags/signOn", json=data, headers=headers)
    response.raise_for_status()
    json_data = response.json()
    return json_data


def refresh_access_token(session: Session, api_base: str, refresh_token: str) -> dict:
    """
    Refresh the access token using the stored refresh token.

    :param session: The requests session to use.
    :param refresh_token: The refresh token to use.

    :return: The refresh response in JSON format.
    """
    headers = {
        "Authorization": f"Bearer {refresh_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
        "nv-tenant-id": static.nv_tenant_id,
    }
    response = session.post(f"{api_base}/ias/v3/token/actions/refresh", headers=headers)
    response.raise_for_status()
    json_data = response.json()
    return json_data

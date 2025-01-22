from requests import Session
from resources.lib.van import static


def get_content_token(
    session: Session, api_base: str, access_token: str, content_id: str
) -> dict:
    """
    Get the content token. This token is still provided by the platform, but seems to act
     as the authentication token that's then passed to the DRM provider for session setup.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.
    :param content_id: The content ID to get the token for.

    :return: The content token response in JSON format.
    """
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "content_id": content_id,
        "type": static.content_device_type,
        "nv-tenant-id": static.nv_tenant_id,
    }
    response = session.post(
        f"{api_base}/ias/v2/content_token", headers=headers, params=params
    )
    response.raise_for_status()
    json_data = response.json()
    return json_data


def setup_session(session: Session, api_base: str, content_token: str) -> dict:
    """
    Setup the streaming session. Final step, where the DRM provider is contacted to setup the session.
    We get a sessionToken and a heartbeat interval for DRM communication.
    If this errors with 1007, there are too many concurrent sessions.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param content_token: The content token to use for session setup.

    :return: The session setup response in JSON format.
    """
    headers = {
        "nv-authorizations": content_token,
        "content-type": "application/json; charset=utf-8",
    }
    if session.device_properties["nagra_device_type"] == "Android":
        headers["User-Agent"] = static.android_nagra_user_agent
    response = session.post(
        f"{api_base}/ssm/v1/sessions/setup", headers=headers, json={}
    )
    response.raise_for_status()
    json_data = response.json()
    return json_data

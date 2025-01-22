from requests import Session
from resources.lib.van import static


def get_channel_list(session: Session, api_base: str, access_token: str) -> dict:
    """
    Get the list of live channels. For now without pagination, since the site uses a limit of 10000.
    Which should be enough for plenty of channels in a single request.
    params are also hardcoded for now, as they are hardcoded on the site as well
     (subject to change in this codebase in the future).

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.

    :return: The channel list in JSON format.
    """
    params = {
        "sort": '[["editorial.tvChannel",1]]',
        "filter": f'{{"technical.deviceType":{{"$in":["{session.device_properties["nagra_device_type"]}"]}}}}',
        "limit": 10000,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    response = session.get(
        f"{api_base}/metadata/delivery/GLOBAL/btv/services",
        params=params,
        headers=headers,
    )
    response.raise_for_status()
    json_data = response.json()
    return json_data

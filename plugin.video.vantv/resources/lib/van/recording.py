from requests import Session


def record_episode(
    session: Session,
    api_base: str,
    access_token: str,
    event_id: str,
    is_protected: bool = False,
) -> None:
    """
    Record an episode. 201 with no content means recording successfully scheduled.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.
    :param event_id: The event ID to record.
    :param is_protected: Whether the recording is protected or not. Seems to be False by default.

    :return: None
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    data = {
        "isProtected": is_protected,
        "eventId": event_id,
    }
    response = session.post(
        f"{api_base}/cdvr/v1/recordings",
        headers=headers,
        json=data,
    )
    response.raise_for_status()
    return


def record_series(session: Session, api_base: str, access_token: str, event_id: str):
    """
    Record a complete series. 201 with no content means recording successfully scheduled.

    :param session: The requests session to use.
    :param api_base: The API base URL.
    :param access_token: The access token to use for authentication.
    :param event_id: The event ID to record.

    :return: None
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Nagra-Device-Type": session.device_properties["nagra_device_type"],
        "Nagra-Target": session.device_properties["nagra_target"],
    }
    data = {
        "seriesType": "SERIES",
        "recordingOptions": ["ALL_EPISODES"],
        "numberOfEpisodesToKeep": 0,
        "eventId": event_id,
    }
    response = session.post(
        f"{api_base}/cdvr/v1/seriesrecordings",
        headers=headers,
        json=data,
    )
    response.raise_for_status()
    return

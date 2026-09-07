import json
import logging
from urllib.parse import urlencode

import aiohttp
import async_timeout
from homeassistant.exceptions import HomeAssistantError

from custom_components.ac_infinity.const import (
    AdvancedSettingsKey,
    AtType,
    DeviceControlKey,
    ModeAndSettingKeys,
    ROOM_TO_ROOM_FAN_MODE_SETTING_ID_STR,
    RoomToRoomFanExtraKeys,
    RoomToRoomFanMode,
)

_LOGGER = logging.getLogger(__name__)

API_URL_LOGIN = "/api/user/appUserLogin"
API_URL_GET_DEVICE_INFO_LIST_ALL = "/api/user/devInfoListAll"
API_URL_GET_DEV_MODE_SETTING = "/api/dev/getdevModeSettingList"
API_URL_ADD_DEV_MODE = "/api/dev/addDevMode"
API_URL_MODE_AND_SETTINGS = "/api/dev/modeAndSetting"
API_URL_GET_DEV_SETTING = "/api/dev/getDevSetting"
API_URL_UPDATE_ADV_SETTING = "/api/dev/updateAdvSetting"


class ACInfinityClient:
    """Encapsulates http calls to the AC Infinity API"""

    def __init__(self, host: str, email: str, password: str) -> None:
        """
        Args:
            host: The base host of the AC Infinity API
            email: The e-mail to log in as, as configured by the user via config_flow
            password: The password to log in with, as configured by the user via config_flow
        """
        self._host = host
        self._email = email
        self._password = password
        self._user_id: str | None = None
        self._session: aiohttp.ClientSession | None = None

    async def login(self):
        """Call the log in endpoint with the configured email and password, and obtain the user id to use for subsequent calls"""
        headers = self.__create_headers(use_auth_token=False)

        # AC Infinity API does not accept passwords greater than 25 characters.
        # The Android/iOS app truncates passwords to accommodate for this.  We must do the same.
        normalized_password: str = self._password[0:25]

        response = await self.__post(
            API_URL_LOGIN,
            {"appEmail": self._email, "appPasswordl": normalized_password},
            headers,
        )
        self._user_id = response["data"]["appId"]

    def is_logged_in(self):
        """returns true if the user id is set, false otherwise"""
        return True if self._user_id else False

    def __ensure_logged_in(self) -> None:
        """Raise when a request requires an authenticated client."""
        if not self.is_logged_in():
            raise ACInfinityClientCannotConnect("AC Infinity client is not logged in.")

    async def get_account_controllers(self):
        """Obtains a list of controllers, including metadata and some sensor values.
        Does not include information related to settings.
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True)
        body = await self.__post(
            API_URL_GET_DEVICE_INFO_LIST_ALL, {"userId": self._user_id}, headers
        )
        return body["data"]

    async def get_device_mode_settings(self, controller_id: str | int, device_port: int):
        """Obtains the settings for a particular port on a controller, which includes information
        like speed, sensor triggers, mode timers, etc...

        Args:
            controller_id: The parent controller id of the port
            device_port: The port on the controller of the settings list to grab
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True)
        body = await self.__post(
            API_URL_GET_DEV_MODE_SETTING, {"devId": controller_id, "port": device_port}, headers
        )
        return body["data"]

    @staticmethod
    def __transfer_values(device_control_keys: list[str], new_values: dict, existing_values: dict):
        updated: dict[str, str | int | bool] = {}
        for key in device_control_keys:
            value = new_values.get(key, existing_values.get(key, 0))
            if value is None:
                updated[key] = 0
            elif isinstance(value, (dict, list)):
                updated[key] = json.dumps(value)
            elif isinstance(value, bool):
                updated[key] = str(value).lower()
            else:
                updated[key] = value

        return updated

    async def update_device_controls(
        self, controller_id: str | int, device_port: int, key_values: dict[str, int]
    ):
        """Sets the provided settings on a port to a new values

        Args:
            controller_id: The parent controller id
            device_port: The port on the controller the device is plugged into
            key_values: The key value pairs of settings to set
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True)
        body = await self.__post(
            API_URL_GET_DEV_MODE_SETTING, {"devId": controller_id, "port": device_port}, headers
        )
        existing_values = body["data"]

        device_control_keys: list[str] = [
            getattr(DeviceControlKey, attr)
            for attr in dir(DeviceControlKey)
            if not attr.startswith('_')
        ]

        updated = self.__transfer_values(device_control_keys, key_values, existing_values)
        _ = await self.__post(f"{API_URL_ADD_DEV_MODE}?{urlencode(updated)}", None, headers)

    async def update_device_settings(
        self, controller_id: str | int, device_port: int, device_name: str, key_values: dict[str, int]
    ):
        """Sets the provided settings on a port to a new values

        Args:
            controller_id: The parent controller id
            device_port: The port on the controller the device is plugged into
            device_name: The name of the device
            key_values: The key value pairs of settings to set
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True)
        body = await self.__post(
            API_URL_GET_DEV_SETTING, {"devId": controller_id, "port": device_port}, headers
        )
        existing_values = body["data"]

        device_settings_keys: list[str] = [
            getattr(AdvancedSettingsKey, attr)
            for attr in dir(AdvancedSettingsKey)
            if not attr.startswith('_')
        ]

        updated = self.__transfer_values(device_settings_keys, key_values, existing_values)
        updated[AdvancedSettingsKey.DEV_NAME] = device_name

        _ = await self.__post(f"{API_URL_UPDATE_ADV_SETTING}?{urlencode(updated)}", None, headers)

    async def update_ai_device_control_and_settings(
        self, controller_id: str | int, device_port: int, key_values: dict[str, int]
    ):
        """Sets the provided settings on a port to a new values

        Args:
            controller_id: id of the controller
            device_port: port of the device
            key_values: The key value pairs of settings to set
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True, use_min_version=True)
        body = await self.__post(
            API_URL_GET_DEV_MODE_SETTING, {"devId": controller_id, "port": device_port}, headers
        )
        existing_values = body["data"]

        flattened = existing_values[DeviceControlKey.DEV_SETTING].copy()
        flattened.update(existing_values)

        device_control_keys: list[str] = [
            getattr(ModeAndSettingKeys, attr)
            for attr in dir(ModeAndSettingKeys)
            if not attr.startswith('_')
        ]

        updated = self.__transfer_values(device_control_keys, key_values, flattened)

        at_type = updated[DeviceControlKey.AT_TYPE]
        match at_type:
            case AtType.OFF:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16,17]"
            case AtType.ON:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16,18]"
            case AtType.AUTO:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[112,16,19,32,98,99]"
            case AtType.TIMER_TO_ON | AtType.TIMER_TO_OFF:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16,20,21]"
            case AtType.CYCLE | AtType.SCHEDULE:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16,22,23,40]"
            case AtType.VPD:
                updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16,81,32,98,99]"
            case _:
                raise ValueError(f"Unable to find setting id string - Unknown atType {at_type}")

        url = f"{API_URL_MODE_AND_SETTINGS}?{urlencode(updated)}"
        _ = await self.__put(url, headers)

    async def update_room_to_room_fan_control(
        self, controller_id: str | int, device_port: int, key_values: dict[str, int]
    ):
        """Sets control values for a room-to-room/through-wall fan (e.g. AC-TWT6, devType 33).

        These devices use the same /api/dev/modeAndSetting endpoint and response shape as
        AI controllers (a flat top-level payload merged with a nested "devSetting" object),
        but the "atType" mode values and their corresponding modeAndSettingIdStr strings are
        entirely different - confirmed via packet capture of the official app. See
        RoomToRoomFanMode and ROOM_TO_ROOM_FAN_MODE_SETTING_ID_STR in const.py.

        Args:
            controller_id: id of the controller
            device_port: port of the device (always 0 for this device type)
            key_values: The key value pairs of settings to set
        """
        self.__ensure_logged_in()

        headers = self.__create_headers(use_auth_token=True, use_min_version=True)
        body = await self.__post(
            API_URL_GET_DEV_MODE_SETTING, {"devId": controller_id, "port": device_port}, headers
        )
        existing_values = body["data"]

        flattened = existing_values[DeviceControlKey.DEV_SETTING].copy()
        flattened.update(existing_values)
        previous_at_type = flattened.get(DeviceControlKey.AT_TYPE)

        # Includes RoomToRoomFanExtraKeys - fields this device's firmware requires that
        # aren't part of the general ModeAndSettingKeys set (confirmed via packet capture;
        # omitting them causes the API to reject the request with a generic failure code).
        device_control_keys: list[str] = [
            getattr(ModeAndSettingKeys, attr)
            for attr in dir(ModeAndSettingKeys)
            if not attr.startswith('_')
        ] + [
            getattr(RoomToRoomFanExtraKeys, attr)
            for attr in dir(RoomToRoomFanExtraKeys)
            if not attr.startswith('_')
        ]

        updated = self.__transfer_values(device_control_keys, key_values, flattened)

        at_type = updated[DeviceControlKey.AT_TYPE]
        if at_type not in ROOM_TO_ROOM_FAN_MODE_SETTING_ID_STR:
            raise ValueError(f"Unable to find setting id string - Unknown room-to-room fan atType {at_type}")

        if at_type != previous_at_type and at_type == RoomToRoomFanMode.MANUAL:
            # Confirmed via capture: transitioning INTO Manual mode from a different mode
            # uses "[16]" alone, distinct from "[18]" used while already in Manual and
            # only adjusting a value (e.g. fan speed) without changing mode. The other
            # modes' entries in ROOM_TO_ROOM_FAN_MODE_SETTING_ID_STR are confirmed correct
            # for their mode-transition case, which is the common path through this method.
            updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = "[16]"
        else:
            updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR] = ROOM_TO_ROOM_FAN_MODE_SETTING_ID_STR[at_type]

        _LOGGER.debug(
            "Room-to-room fan control update: previous_at_type=%s new_at_type=%s "
            "idStr=%s key_values=%s",
            previous_at_type, at_type, updated[ModeAndSettingKeys.MODE_AND_SETTING_ID_STR], key_values,
        )

        url = f"{API_URL_MODE_AND_SETTINGS}?{urlencode(updated)}"
        _ = await self.__put(url, headers)

    async def close(self) -> None:
        """Close the session when done"""
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def __get_session(self) -> aiohttp.ClientSession:
        """Get or create the HTTP session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(raise_for_status=False)
        return self._session

    async def __post(self, path, post_data, headers):
        """generically make a post request to the AC Infinity API"""
        session = await self.__get_session()
        async with async_timeout.timeout(10), session.post(
            f"{self._host}{path}", data=post_data, headers=headers
        ) as response:
            if response.status != 200:
                raise ACInfinityClientCannotConnect

            body = await response.json()
            if body["code"] != 200:
                if path == API_URL_LOGIN:
                    raise ACInfinityClientInvalidAuth
                else:
                    raise ACInfinityClientRequestFailed(body)

            return body

    async def __put(self, path, headers):
        """generically make a put request to the AC Infinity API"""
        session = await self.__get_session()
        async with async_timeout.timeout(10), session.put(
            f"{self._host}{path}", headers=headers
        ) as response:
            if response.status != 200:
                raise ACInfinityClientCannotConnect

            body = await response.json()
            if body["code"] != 200:
                raise ACInfinityClientRequestFailed(body)

            return body

    def __create_headers(self, use_auth_token: bool, use_min_version: bool = False) -> dict:
        """Creates a header object to use in a request to the AC Infinity API"""
        # noinspection SpellCheckingInspection
        headers: dict = {
            "User-Agent": "okhttp/4.12.0",
        }

        if use_auth_token:
            headers["token"] = self._user_id

        if use_min_version:
            headers["minversion"] = "3.5"

        return headers


class ACInfinityClientCannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class ACInfinityClientInvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


class ACInfinityClientRequestFailed(HomeAssistantError):
    """Error to indicate a request failed"""

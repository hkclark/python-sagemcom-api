""" Python wrapper for the Sagemcom API """
import aiohttp
import asyncio

import logging
import time
import hashlib
import math
import random
import json

from collections import namedtuple
from enum import Enum


class AuthenticationMethods(Enum):
    MD5 = 1
    SHA512 = 2


class UnauthorizedException(Exception):
    pass


class BadRequestException(Exception):
    pass


class UnknownException(Exception):
    pass


Device = namedtuple(
    "Device", ["mac_address", "ip_address", "ipv4_addresses", "ipv6_addresses", "name", "address_source", "interface", "active",
               "user_friendly_name", "detected_device_type", "user_device_type"])


class Sagemcom_Client(object):
    """ Interface class for the Sagemcom API """

    def __init__(self, host, username, password, authentication_method=AuthenticationMethods.MD5):
        """
        Constructor

        :param host: the host of your Sagemcom router
        :param username: the username for your Sagemcom router
        :param password: the password for your Sagemcom router
        :param authentication_method: the authentication method of your Sagemcom router
        """

        self.host = host
        self.username = username
        self.authentication_method = authentication_method

        self._password_hash = self.__generate_hash(password)

        self._current_nonce = None
        self._server_nonce = ''
        self._session_id = 0
        self._request_id = -1

    def __generate_nonce(self):
        """ Generate pseudo random number (nonce) to avoid replay attacks """
        self._current_nonce = math.floor(random.randrange(0, 1) * 500000)

    def __generate_request_id(self):
        """ Generate sequential request ID """
        self._request_id += 1

    def __generate_hash(self, value):
        """ Hash value with MD5 or SHA12 and return HEX """
        bytes_object = bytes(value, encoding='utf-8')

        if self.authentication_method is AuthenticationMethods.MD5:
            return hashlib.md5(bytes_object).hexdigest()

        if self.authentication_method is AuthenticationMethods.SHA512:
            return hashlib.sha512(bytes_object).hexdigest()

        return value

    def __get_credential_hash(self):
        """ Build credential hash """
        return self.__generate_hash(self.username + ":" + self._server_nonce + ":" + self._password_hash)

    def __generate_auth_key(self):
        """ Build auth key """
        credential_hash = self.__get_credential_hash()
        auth_string = str(credential_hash) + ":" + str(self._request_id) + \
            ":" + str(self._current_nonce) + ":JSON:/cgi/json-req"

        self._auth_key = self.__generate_hash(auth_string)

    def __get_response_error(self, response):
        """ TODO """
        try:
            value = response['reply']['error']
        except KeyError:
            value = None

        return value

    def __get_response_value(self, response, index=0):
        """ TODO """
        try:
            value = response['reply']['actions'][index]["callbacks"][index]["parameters"]
        except KeyError:
            value = None

        return value

    async def __api_request_async(self, actions, priority=False):
        """ Build request to the internal JSON-req API """

        self.__generate_request_id()
        self.__generate_nonce()
        self.__generate_auth_key()

        api_host = f"http://{self.host}/cgi/json-req"

        payload = {
            "request": {
                "id": self._request_id,
                "session-id": str(self._session_id),
                "priority": priority,
                "actions": actions,
                "cnonce": self._current_nonce,
                "auth-key": self._auth_key
            }
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(api_host, data="req=" + json.dumps(payload, separators=(',', ':'))) as response:

                # Throw Bad Request expection
                if (response.status is 400):
                    result = await response.text()
                    print(result)

                if (response.status is not 200):
                    result = await response.text()
                    print(result)

                if (response.status is 200):
                    result = await response.json()
                    error = self.__get_response_error(result)

                    if (error['description'] != 'XMO_REQUEST_NO_ERR'):
                        print(error)

                return result

    async def login(self):
        actions = {
            "method": "logIn",
            "parameters": {
                "user": self.username,
                "persistent": "true",
                "session-options": {
                    "nss": [
                        {
                            "name": "gtw",
                            "uri": "http://sagemcom.com/gateway-data"
                        }
                    ],
                    "language": "ident",
                    "context-flags": {
                        "get-content-name": True,
                        "local-time": True
                    },
                    "capability-depth": 2,
                    "capability-flags": {
                        "name": True,
                        "default-value": False,
                        "restriction": True,
                        "description": False
                    },
                    "time-format": "ISO_8601",
                    "write-only-string": "_XMO_WRITE_ONLY_",
                    "undefined-write-only-string": "_XMO_UNDEFINED_WRITE_ONLY_"
                }
            }
        }

        response = await self.__api_request_async([actions], True)
        data = self.__get_response_value(response)

        if data['id'] is not None and data['nonce'] is not None:
            self._session_id = data['id']
            self._server_nonce = data['nonce']
            return True
        else:
            return False

    async def get_device_info(self):
        actions = {
            "id": 0,
            "method": "getValue",
            "xpath": "Device/DeviceInfo"
        }

        response = await self.__api_request_async([actions], False)
        data = self.__get_response_value(response)

        return data

    async def get_port_mappings(self):
        actions = {
            "id": 0,
            "method": "getValue",
            "xpath": "Device/NAT/PortMappings"
        }

        response = await self.__api_request_async([actions], False)
        data = self.__get_response_value(response)

        return data

    async def get_hosts(self):
        actions = {
            "id": 0,
            "method": "getValue",
            "xpath": "Device/Hosts/Hosts",
            "options": {
                "capability-flags": {
                      "interface": True,
                }
            }
        }

        response = await self.__api_request_async([actions], False)
        data = self.__get_response_value(response)

        return data

    async def reboot(self):
        actions = {
            "method": "reboot",
            "xpath": "Device",
            "parameters": {
                "source": "GUI"
            }
        }

        response = await self.__api_request_async([actions], False)
        data = self.__get_response_value(response)

        return data

    def parse_devices(self, data, only_active=True) -> list:

        devices = []

        for device in data:
            if not only_active or device['Active']:

                device = Device(
                    mac_address=device['PhysAddress'].upper(),
                    ip_address=device['IPAddress'],
                    ipv4_addresses=device['IPv4Addresses'],
                    ipv6_addresses=device['IPv6Addresses'],
                    address_source=device['AddressSource'],
                    name=device['UserHostName'] or device['HostName'],
                    interface=device['InterfaceType'],
                    active=device['Active'],
                    user_friendly_name=device['UserFriendlyName'],
                    detected_device_type=device['DetectedDeviceType'],
                    user_device_type=device['UserDeviceType']
                )

                devices.append(device)

        return devices